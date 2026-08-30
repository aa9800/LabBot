"""실제 Raspbot(Raspberry Pi 5 + Yahboom Raspbot)용 HAL.

sim/hal_sim.py, isaac_hal.py와 반드시 같은 5개 메서드
(read_line_sensors / read_ultrasonic / try_read_qr / set_motion / stop)를
같은 시그니처로 구현한다 — controller.py(PatrolController)는 한 글자도 고치지 않는다.

여기 있는 GPIO 핀 번호·I2C 라이브러리 호출·카메라 설정값은 전부 로봇에 실제로 설치된
Yahboom 공식 데모 노트북에서 직접 읽어와 그대로 옮긴 것이다(추측 없음). 확인한 출처:

- 초음파(Trig=16, Echo=18, BOARD 모드, 0.03초 타임아웃, distance_cm = (t2-t1)*340/2*100):
  ~/Yahboom_project/Raspbot/2.Hardware Control course/04.Ultrasonic Ranging/Ultrasonic Ranging.ipynb
- 라인트래킹 4채널(BOARD 모드, Tracking_Right1=11, Tracking_Right2=7,
  Tracking_Left1=13, Tracking_Left2=15 — 안쪽 두 개가 "1", 바깥쪽 두 개가 "2"):
  ~/Yahboom_project/Raspbot/2.Hardware Control course/07.Tracking/Tracking.ipynb
- 모터: YB_Pcb_Car.YB_Pcb_Car().Control_Car(speed1, speed2) — 부호 있는 값,
  양수=전진/음수=후진을 라이브러리가 알아서 처리하고 I2C로 STM8 MCU에 전달한다:
  ~/Yahboom_project/Raspbot/2.Hardware Control course/07.Tracking/YB_Pcb_Car.py
- QR: picamera2.Picamera2() + pyzbar.decode():
  ~/Yahboom_project/Raspbot/3.AI Vision course/06.QR code recognition/QR code recognition.ipynb

(2026-08-26, Raspberry Pi Connect Remote shell로 로봇에 직접 접속해서 위 노트북들을 직접
열어 확인함 — 로봇이 도착하기 전까지는 이 파일이 NotImplementedError만 던지는 자리였다.)

라인트래킹 센서가 "선을 감지"할 때 GPIO 입력이 LOW(False)가 되는 반사형 IR 모듈이라는 것도
같은 노트북의 주석("四路循迹引脚电平状态"/이하 상태표)에서 확인했다 — 그래서 아래에서는
`not GPIO.input(pin)`으로 뒤집어서 "선 위에 있으면 True"로 SimHAL/IsaacHAL과 의미를 맞춘다.

## set_motion(speed, turn) 변환 방식 (엔지니어링 결정, 실측 아님)

controller.py는 SPEED=70, TURN_GAIN=90 같은 값을 그대로 내려보낸다 — 이 값들은 이미
Yahboom 데모들이 Car_Run(70, 70)처럼 직접 쓰는 0~100 PWM 스케일과 같은 자릿수라서,
속도(전후진)와 조향(좌우)을 받아서 양쪽 바퀴 모터를 구동한다.
각 바퀴에 필요한 스칼라 차동값을 즉시 YB_Pcb_Car로 내린다. 이건 하드웨어 사양이 아니라
이 프로젝트에서 고른 변환 공식이라는 점을 분명히 해둔다.
"""
import os
import statistics
import threading
import time
from collections import deque

import RPi.GPIO as GPIO
import YB_Pcb_Car
from frame_broker import FrameBroker

# ── 초음파 ──────────────────────────────────────────────────────────
TRIG_PIN = 16
ECHO_PIN = 18
ECHO_TIMEOUT_S = 0.03  # 공식 데모와 동일 — 이 이상 걸리면 에코 없음으로 보고 포기
# 중앙값을 낼 창 크기. 홀수여야 한다. 3이면 20Hz 기준 약 0.15초 뒤처지는 대신
# 튄 판독 하나는 완전히 무시된다. 5로 키우면 더 안정적이지만 반응이 0.25초 늦다.
MEDIAN_WINDOW = 3
SOUND_SPEED_M_S = 340
NO_OBSTACLE_CM = 999.0  # 다른 HAL들과 동일한 "장애물 없음" 값(OBSTACLE_STOP_DISTANCE=40보다 훨씬 큼)

# ── 라인트래킹 (BOARD 모드) ──────────────────────────────────────────
TRACKING_LEFT_OUTER = 15   # Tracking_Left2  — 왼쪽 바깥쪽
TRACKING_LEFT_INNER = 13   # Tracking_Left1  — 왼쪽 안쪽
TRACKING_RIGHT_INNER = 11  # Tracking_Right1 — 오른쪽 안쪽
TRACKING_RIGHT_OUTER = 7   # Tracking_Right2 — 오른쪽 바깥쪽

# ── 모터 믹싱 ────────────────────────────────────────────────────────
MOTOR_SPEED_LIMIT = 100  # YB_Pcb_Car 데모들이 쓰는 PWM 스케일(0~100)의 상한

# ── 경보 부저 (BOARD 모드) ───────────────────────────────────────────
# Yahboom 공식 데모 `2.Hardware Control course/01.Drive buzzer/Buzzer_test.ipynb` 기준.
# 패시브 부저라서 단순 HIGH/LOW로는 소리가 안 나고 PWM으로 음을 만들어야 한다.
BUZZER_PIN = 32
BUZZER_FREQ_HZ = 440
BUZZER_DUTY = 50  # 듀티비가 곧 음량 — 0이면 무음

# ── 카메라/QR ────────────────────────────────────────────────────────
# ov5647 센서는 2592x1944(500만 화소)까지 낼 수 있는데 오랫동안 320x240만
# 썼다. 센서 능력의 1.6%다. 모델 입력을 416으로 올려도 240줄짜리 그림을
# 늘려 넣는 것이라 없는 디테일이 생기지 않는다 — 카메라부터 올려야 한다.
# 캡처를 키우면 색변환과 JPEG 인코딩 비용이 같이 늘어나므로 환경변수로
# 조절 가능하게 두고 실측해서 정한다.
def _env_size(name, default_w, default_h):
    raw = os.environ.get(name, "")
    if "x" in raw:
        try:
            w, h = raw.lower().split("x")
            return (int(w), int(h))
        except ValueError:
            pass
    return (default_w, default_h)


CAMERA_SIZE = _env_size("LABKEEPER_CAMERA_SIZE", 640, 480)
# 색감 튜닝용 — 화면이 창백/청록빛으로 보이면 이 값들을 조정한다.
# CAMERA_SATURATION: 1.0이 기본, 낮을수록 색이 빠짐(창백함) -> 올리면 색이 진해짐.
# CAMERA_AWB_MODE: "Auto"가 기본. 여전히 색감이 이상하면 "Indoor"/"Tungsten"/"Fluorescent"/
#                  "Daylight"/"Cloudy" 중 조명 환경에 맞는 걸로 바꿔본다.
CAMERA_SATURATION = 1.4
CAMERA_AWB_MODE = "Auto"


class RealHAL:
    def __init__(self, enable_camera=True):
        """enable_camera=False로 두면 카메라 초기화를 건너뛴다 — 순찰 로직(라인트래킹/
        초음파/모터)만 먼저 검증하고 싶을 때, 또는 이 로봇 개체에 카메라가 아직 물리적으로
        안 붙어있을 때 쓴다. try_read_qr()은 그 경우 항상 None을 돌려준다."""
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(ECHO_PIN, GPIO.IN)
        GPIO.setup(TRIG_PIN, GPIO.OUT)
        for pin in (TRACKING_LEFT_OUTER, TRACKING_LEFT_INNER, TRACKING_RIGHT_INNER, TRACKING_RIGHT_OUTER):
            GPIO.setup(pin, GPIO.IN)

        # 경보 부저 — PWM 객체를 한 번만 만들어두고 듀티비만 0/50으로 여닫는다.
        # (울릴 때마다 PWM을 새로 start/stop하면 첫 음이 씹히는 경우가 있다)
        self._buzzer_pwm = None
        try:
            GPIO.setup(BUZZER_PIN, GPIO.OUT)
            self._buzzer_pwm = GPIO.PWM(BUZZER_PIN, BUZZER_FREQ_HZ)
            self._buzzer_pwm.start(0)  # 듀티 0 = 무음 대기
        except Exception as e:
            print(f"[RealHAL] 부저 초기화 실패: {e}")

        self._init_leds()

        self.car = YB_Pcb_Car.YB_Pcb_Car()
        self.last_speed = 0.0
        self.last_turn = 0.0
        self.cam_pan = 90
        self.cam_tilt = 90
        self._camera_stop = threading.Event()
        # 서보를 목표까지 부드럽게 데려가는 스레드용 상태.
        self._servo_target = {}        # 채널 -> 목표 각도
        self._servo_now = {}           # 채널 -> 현재 보낸 각도
        self._servo_wake = threading.Event()
        self._servo_thread = None
        self._servo_dir = {}           # 채널 -> -1/0/+1, 누르고 있는 동안 계속 흐른다
        # 프레임을 받아 '최근 탐지 네모를 얹은 JPEG'를 돌려주는 함수. run_real이 건다.
        self._ai_overlay_encoder = None
        # 초음파는 한 발씩 쏘면 값이 심하게 튄다. 최근 몇 발의 중앙값을 쓴다.
        self._distance_history = deque(maxlen=MEDIAN_WINDOW)

        try:
            # 시작 자세는 중앙. 여기서 한 번 직접 보내고 서보 스레드의 '현재값'도
            # 같이 맞춰둔다 — 안 그러면 첫 명령 때 어디서 출발할지 몰라 튄다.
            hw_pan = (180 - 90) if self.PAN_INVERT else 90
            self.car.Ctrl_Servo(self.SERVO_TILT, 90)
            self.car.Ctrl_Servo(self.SERVO_PAN, hw_pan)
            self._servo_now[self.SERVO_TILT] = 90
            self._servo_now[self.SERVO_PAN] = hw_pan
            self._servo_target[self.SERVO_TILT] = 90
            self._servo_target[self.SERVO_PAN] = hw_pan
        except Exception:
            pass

        self._picam2 = None
        self._pyzbar = None
        self._cv2 = None
        self._stream_server = None
        self._hog = None
        self._obstacle_classifier = None
        self.frame_broker = FrameBroker()
        self._motion_lock = threading.Lock()
        # 모터와 서보가 같은 I2C 버스로 야붐 MCU에 붙어 있다. 제어 루프(20Hz)와
        # 웹의 카메라 명령이 서로 다른 스레드에서 동시에 쓰면 MCU가 PWM을 흔들어
        # 서보가 부르르 떤다. 모든 I2C 명령을 이 락으로 한 줄로 세운다.
        self._i2c_lock = threading.Lock()
        self._is_stopped = False   # 이미 멈춰 있으면 정지 명령을 또 보내지 않는다
        self._motion_prev_gray = None
        self._camera_thread = None
        self._last_qr_time = 0.0
        self._last_qr_result = None
        if enable_camera:
            from picamera2 import Picamera2
            import libcamera
            from pyzbar import pyzbar
            import cv2
            import stream_server
            import notify_supabase

            self._cv2 = cv2
            self._stream_server = stream_server
            self._pyzbar = pyzbar
            # SR-03(사람 감지) 안전 이벤트용 — 외부 계정/모델 다운로드 없이 OpenCV 내장
            # HOG+SVM 보행자 검출기를 사용한다(Roboflow 등 커스텀 모델로 나중에 교체 가능).
            self._hog = cv2.HOGDescriptor()
            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self._picam2 = Picamera2()
            config = self._picam2.create_preview_configuration(
                main={"format": "BGR888", "size": CAMERA_SIZE},
                controls={
                    "FrameDurationLimits": (33333, 33333),  # 30fps 하드웨어 고정
                    "AwbEnable": True,
                    "AwbMode": getattr(libcamera.controls.AwbModeEnum, CAMERA_AWB_MODE),
                    "Saturation": CAMERA_SATURATION,
                }
            )
            config["transform"] = libcamera.Transform(hflip=1, vflip=1)
            self._picam2.configure(config)
            self._picam2.start()

            # 초경량 로컬 MJPEG 스트리밍 서버 시작 (포트 8080) & 로봇 로컬 IP 보고
            try:
                stream_server.start_stream_server(port=8080)
                notify_supabase.report_local_ip()
            except Exception as e:
                print(f"[RealHAL] 스트리밍 서버 시작 또는 IP 보고 실패: {e}")

            # 카메라 캡처를 컨트롤 틱과 완전히 분리된 백그라운드 스레드로 돌린다.
            # 장애물/순찰 상태와 무관하게 항상 30fps로 최신 프레임을 캡처하여 스트림 버퍼를 갱신한다.
            self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
            self._camera_thread.start()

    # 아무도 스트림을 안 볼 때도 /snapshot은 최신 그림을 줘야 하므로 완전히 멈추지는
    # 않고 이 간격으로만 인코딩한다(초당 2장).
    IDLE_ENCODE_INTERVAL_S = 0.5

    def _camera_loop(self):
        """항상 돌아가는 카메라 캡처 루프 — capture_array()의 하드웨어 블로킹(33.3ms)에 정확히 동기화된 무진동 30fps."""
        last_encode = 0.0
        while not self._camera_stop.is_set():
            try:
                frame = self._picam2.capture_array()
                if self._cv2 is not None and self._stream_server is not None:
                    # picamera2의 RGB 출력을 OpenCV가 기대하는 BGR로 변환 (손이 파란색/초록색으로 보이는 스머프 색상 왜곡 해결)
                    bgr_frame = self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2BGR)
                    # AI·QR·움직임 감지는 항상 최신 프레임이 필요하다. 이건 참조만
                    # 넘기는 것이라 사실상 공짜다.
                    self.frame_broker.publish(bgr_frame)

                    # JPEG 인코딩은 이 루프에서 제일 비싼 일이다. 보는 사람이 없으면
                    # 만들어봐야 그대로 버려지므로 초당 2장으로 떨어뜨린다. 관리자
                    # 화면을 열면 즉시 30fps로 돌아온다.
                    now = time.time()
                    if (self._stream_server.camera_has_viewers()
                            or now - last_encode >= self.IDLE_ENCODE_INTERVAL_S):
                        last_encode = now
                        # 품질 50 — 초고속 인코딩 및 자연스러운 색상 송출
                        _, jpeg = self._cv2.imencode(
                            ".jpg", bgr_frame, [int(self._cv2.IMWRITE_JPEG_QUALITY), 50, int(self._cv2.IMWRITE_JPEG_OPTIMIZE), 0]
                        )
                        self._stream_server.set_camera_frame(jpeg.tobytes())

                    # AI 오버레이는 예전에 추론이 끝난 프레임(8fps)에만 그렸다.
                    # 그러면 네모뿐 아니라 화면 자체가 8fps 라 뚝뚝 끊긴다.
                    # 이제 여기서 30fps 프레임마다 '가장 최근 탐지 결과'를 얹는다.
                    # 네모는 최대 125ms 뒤처지지만 영상이 부드러워진다 — 실시간
                    # 탐지 화면은 보통 이렇게 만든다.
                    if (self._ai_overlay_encoder is not None
                            and self._stream_server.ai_has_viewers()):
                        try:
                            ai_jpeg = self._ai_overlay_encoder(bgr_frame)
                            if ai_jpeg:
                                self._stream_server.set_ai_frame(ai_jpeg)
                        except Exception as overlay_err:
                            print(f"[RealHAL] AI 오버레이 실패(무시): {overlay_err}")
            except Exception as e:
                print(f"[RealHAL] 카메라 캡처 실패: {e}")
                time.sleep(0.2)  # 에러 시 CPU 폭주 방지 대기

    # ── PatrolController가 실제로 호출하는 5개 메서드 ──────────────────

    def capture_frame(self):
        """백그라운드 카메라 스레드가 가장 최근에 캡처해둔 프레임을 안전하게 돌려준다(QR 디코딩/스냅샷용)."""
        if self._picam2 is None:
            return None
        snapshot = self.frame_broker.latest(copy=True)
        return snapshot.frame if snapshot is not None else None

    def read_line_sensors(self):
        """(left, mid_left, mid_right, right) — True면 그 센서가 지금 선 위에 있다는 뜻.
        GPIO.input()이 LOW(0)일 때 선을 감지한 것이므로 not으로 뒤집는다."""
        return (
            not GPIO.input(TRACKING_LEFT_OUTER),
            not GPIO.input(TRACKING_LEFT_INNER),
            not GPIO.input(TRACKING_RIGHT_INNER),
            not GPIO.input(TRACKING_RIGHT_OUTER),
        )

    def read_ultrasonic(self):
        """cm 단위 거리. 최근 몇 번의 중앙값을 돌려준다.

        HC-SR04 는 한 발씩 쏘면 값이 심하게 튄다. 같은 자리에서 실측한 연속
        판독이 이랬다:

            999.0  32.4  31.2  21.0  31.3  31.2  35.2  55.5  31.5  85.2

        999 는 에코를 못 받은 것이고, 21/55/85 는 바닥이나 모서리에 빗맞은
        것이다. 이 값을 그대로 회피 판단에 넣으면 아무것도 없는데 한 번 튄
        판독에 멈춰 선다("문턱을 보고 안 간다"는 증상의 상당 부분이 이것이다).

        중앙값은 튄 값 하나에 흔들리지 않는다 — [31, 21, 31] 의 중앙값은 31 이다.
        새로 쏘는 건 매번 한 발뿐이라 측정 비용은 늘지 않고, 대신 판단이
        MEDIAN_WINDOW 틱만큼(20Hz 기준 약 0.15초) 뒤처진다.
        """
        raw = self._read_ultrasonic_once()
        self._distance_history.append(raw)
        return statistics.median(self._distance_history)

    def _read_ultrasonic_once(self):
        """센서를 한 발 쏘고 그대로 돌려준다. 에코 타임아웃이면 NO_OBSTACLE_CM —
        -1을 그대로 돌려주면 controller.py가 '아주 가까운 장애물'로 오판해서 즉시 멈춘다."""
        GPIO.output(TRIG_PIN, GPIO.LOW)
        time.sleep(0.000002)
        GPIO.output(TRIG_PIN, GPIO.HIGH)
        time.sleep(0.000015)
        GPIO.output(TRIG_PIN, GPIO.LOW)

        # 여기서 sleep(0) 으로 GIL 을 놓아주면 안 된다. 아래 두 번째 루프는 에코
        # 펄스의 '길이'를 재는 구간이라, 그 사이 다른 스레드가 끼어들면 그만큼
        # 시간이 부풀려져 거리가 길게 나온다. 2026-08-30 에 그걸 넣었다가 판독이
        # 통째로 망가졌다:
        #
        #     서비스 정지 상태   120/120 판독이 전부 15~20cm   (노이즈 0)
        #     서비스 가동 상태   20 / 31 / 55 / 85 / 999 뒤죽박죽
        #
        # "문턱을 보고 안 간다"는 증상의 실제 원인이 이것이었다. 센서는 멀쩡했다.
        # 굶김을 걱정했지만 30cm 짜리 에코는 1.7ms 뿐이라(20Hz 에서 3% 점유)
        # 붙잡고 있어도 문제가 없다. 에코가 아예 없을 때만 30ms 를 쓴다.
        t_send = time.time()
        while not GPIO.input(ECHO_PIN):
            if time.time() - t_send > ECHO_TIMEOUT_S:
                return NO_OBSTACLE_CM
        t1 = time.time()
        while GPIO.input(ECHO_PIN):
            if time.time() - t1 > ECHO_TIMEOUT_S:
                return NO_OBSTACLE_CM
        t2 = time.time()
        return ((t2 - t1) * SOUND_SPEED_M_S / 2) * 100

    def find_qr_boxes(self, frame):
        """프레임에서 QR 위치와 값을 찾는다. 화면에 그려주기 위한 것.

        scan_qr_now 와 달리 값만이 아니라 위치도 돌려준다. 사용자가 "QR 인식이
        안 된다"고 할 때, 화면에 네모가 그려지면 "보이지만 각도·거리 문제",
        안 그려지면 "아예 안 보임"으로 원인이 바로 갈린다.
        """
        if frame is None or self._pyzbar is None:
            return []
        try:
            gray = (self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
                    if self._cv2 is not None else frame)
            out = []
            for code in self._pyzbar.decode(gray):
                r = code.rect
                out.append({
                    "x": int(r.left), "y": int(r.top),
                    "w": int(r.width), "h": int(r.height),
                    "text": code.data.decode("utf-8", "replace"),
                })
            return out
        except Exception as e:
            print(f"[RealHAL] QR 위치 탐색 실패(무시): {e}")
            return []

    def scan_qr_now(self):
        """웹 버튼 클릭 시 온디맨드로 단 1회 현재 카메라 프레임에서 QR을 정밀 디코딩한다."""
        frame = self.capture_frame()
        if frame is None or self._pyzbar is None:
            return None
        try:
            # Grayscale 변환으로 pyzbar 디코딩 속도 5배 향상 및 인식률 극대화
            if self._cv2 is not None:
                gray = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
            else:
                gray = frame
            codes = self._pyzbar.decode(gray)
            if not codes:
                return None
            return codes[0].data.decode("utf-8")
        except Exception as e:
            print(f"[RealHAL] QR 디코딩 실패: {e}")
            return None

    def try_read_qr(self):
        """온디맨드 구조 전환: 평상시 자동 주행/대기 중에는 무거운 QR 연산을 0%로 차단하여 발열 및 쓰로틀링 방지."""
        return None

    def detect_person(self):
        """SR-03 안전 이벤트용 — 현재 프레임에 사람이 있으면 True.
        OpenCV 내장 HOG+SVM 보행자 검출기 사용(외부 모델 다운로드/계정 불필요).
        나중에 Roboflow 등 커스텀 모델로 교체하려면 이 메서드 내부만 바꾸면 된다
        (호출부인 run_real.py는 True/False만 알면 되므로 영향 없음)."""
        frame = self.capture_frame()
        if frame is None or self._hog is None:
            return False
        try:
            boxes, _weights = self._hog.detectMultiScale(
                frame, winStride=(8, 8), padding=(8, 8), scale=1.05
            )
            return len(boxes) > 0
        except Exception as e:
            print(f"[RealHAL] 사람 감지 실패: {e}")
            return False

    def detect_motion(self):
        """야간 정차 감시용 저비용 움직임 감지.

        160x120 회색조 프레임만 비교하므로 HOG 사람 검출보다 훨씬 가볍다. 카메라가
        움직이는 주행 중에는 호출하지 않고, 야간 정차 상태에서만 run_real.py가
        약 2Hz로 호출한다.
        """
        frame = self.capture_frame()
        if frame is None or self._cv2 is None:
            return False
        try:
            gray = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
            gray = self._cv2.resize(gray, (160, 120), interpolation=self._cv2.INTER_AREA)
            gray = self._cv2.GaussianBlur(gray, (7, 7), 0)
            with self._motion_lock:
                previous = self._motion_prev_gray
                self._motion_prev_gray = gray
            if previous is None:
                return False
            diff = self._cv2.absdiff(previous, gray)
            _, mask = self._cv2.threshold(diff, 24, 255, self._cv2.THRESH_BINARY)
            changed_ratio = self._cv2.countNonZero(mask) / float(mask.size)
            return changed_ratio >= 0.025
        except Exception as e:
            print(f"[RealHAL] 움직임 감지 실패: {e}")
            return False

    def reset_motion_baseline(self):
        """주행/카메라 조작 뒤 첫 프레임을 움직임으로 오인하지 않게 기준을 버린다."""
        with self._motion_lock:
            self._motion_prev_gray = None

    def classify_obstacle(self):
        """우회 직전 카메라로 사람 여부만 구분한다.

        현재 장비에는 전방 초음파 하나뿐이라 물체의 정확한 종류를 안정적으로 분류할
        수는 없다. 대신 사람은 가까이 우회하지 않고 통과할 때까지 정지시키고, 나머지
        물체만 저속 좌우 스캔 우회 대상으로 분류한다.
        """
        if callable(self._obstacle_classifier):
            try:
                return self._obstacle_classifier()
            except Exception as error:
                print(f"[RealHAL] AI 장애물 분류 실패, HOG fallback 사용: {error}")
        return "person" if self.detect_person() else "object"

    def set_obstacle_classifier(self, classifier):
        """통합 Edge AI의 최신 결과를 장애물 종류 판단에 연결한다."""
        self._obstacle_classifier = classifier

    def set_motion(self, speed, turn):
        """아케이드 믹싱(모듈 docstring 참고) 후 클램프해서 Control_Car로 보낸다."""
        self.last_speed = float(speed)
        self.last_turn = float(turn)
        left = speed + turn
        right = speed - turn
        left = max(-MOTOR_SPEED_LIMIT, min(MOTOR_SPEED_LIMIT, left))
        right = max(-MOTOR_SPEED_LIMIT, min(MOTOR_SPEED_LIMIT, right))
        with self._i2c_lock:
            self.car.Control_Car(int(left), int(right))
        self._is_stopped = (int(left) == 0 and int(right) == 0)

    def stop(self):
        """정지. 이미 멈춰 있으면 I2C에 아무것도 보내지 않는다.

        제어 루프는 임무가 없을 때 매 틱(20Hz) stop()을 부른다. 예전에는 그때마다
        Car_Stop()이 I2C로 나가서, 초당 20번의 불필요한 전송이 서보 명령과 뒤엉켜
        카메라가 떨렸다. 상태가 바뀔 때만 실제로 보낸다.
        """
        self.last_speed = 0.0
        self.last_turn = 0.0
        if self._is_stopped:
            return
        with self._i2c_lock:
            self.car.Car_Stop()
        self._is_stopped = True

    # 배선을 실측으로 두 번 고쳤다.
    #
    # 1) 처음에는 팬을 2번으로 보내고 있어서 "명령은 나가는데 안 움직인다" 였다.
    #    채널 1~4 를 하나씩 단독으로 돌려보니 팬은 4번에 물려 있었다.
    # 2) 그런데 4번으로 옮기니 팬이 심하게 떨었다. 카메라 영상의 프레임간 이동을
    #    재서 커넥터를 맞바꿔가며 확인한 결과, 떨림이 서보가 아니라 채널을 따라갔다.
    #
    #      좌우서보 + 채널4   같은 값 반복에도 3.915px (최대 21.9)   떨림
    #      좌우서보 + 채널1   0.003px                               정상
    #      상하서보 + 채널1   0.026px                               정상
    #      상하서보 + 채널4   0.524px (최대 7.5)                    떨림
    #      8도 이동   채널4 뒤집힘 11.8회 / 59px · 채널1 0.0회 / 20px
    #
    #    즉 확장보드의 채널 4 PWM 출력이 불량이다. 서보 두 개는 멀쩡하다.
    #    그래서 커넥터를 옮겼다. 채널 4 는 쓰지 않는다.
    #
    # 최종 배선(2026-08-30): 채널 1 = 좌우, 채널 2 = 상하, 채널 3·4 미사용.
    SERVO_PAN = 1   # 좌우
    SERVO_TILT = 2  # 상하

    # 틸트는 거치대가 먼저 걸려서 끝까지 돌리면 서보가 스톨(윙 소리만 나고 정지)한다.
    # 팬은 기구 간섭이 없어 전 범위를 쓴다.
    TILT_MIN, TILT_MAX = 35, 145
    PAN_MIN, PAN_MAX = 0, 180

    # 웹이 목표 각도만 알려주고, 실제로 그쪽으로 데려가는 일은 로봇이 한다.
    # 예전에는 웹이 4도씩 120ms 간격으로 직접 보냈는데, 서보는 4도를 7ms 만에
    # 끝내고 113ms 를 멈춰 있어서 초당 8번 "움직임-정지"를 반복했다. 공유기를
    # 거치면서 왕복이 33ms(최대 65ms)로 들쭉날쭉해 간격도 흔들렸다.
    # 이제 이 스레드가 60Hz 로 목표까지 촘촘히 좁혀간다 — 네트워크 지연이
    # 움직임에 드러나지 않고, 웹은 아무 때나 목표만 바꾸면 된다.
    SERVO_TICK_S = 1.0 / 60
    SERVO_DEG_PER_S = 150.0        # 큰 점프를 나눠서 갈 때의 속도

    # 이 각도 이하로 움직일 때는 목표를 그대로 던지고 서보가 알아서 가게 둔다.
    # SG90 은 자체적으로 부드러운 가속-감속 곡선을 만든다(실측: 8도 이동에
    # +0.3 +1.2 +2.4 +5.7 +4.0 +2.5 +0.9 +0.1). 그걸 등속 스텝으로 쪼개면
    # 오히려 덜 부드러워진다. 웹의 화살표 조작은 한 번에 4도씩이라 대부분
    # 여기에 걸려서 서보 고유 곡선을 그대로 쓴다.
    SERVO_DIRECT_DEG = 15.0

    # 화살표를 누르고 있는 동안의 이동 속도. 이 모드에서는 서보가 목표에 닿기
    # 전에 다음 목표가 오므로 멈추지 않고 계속 흐른다 — 웹이 4도씩 끊어 보내던
    # 계단식 움직임이 사라진다.
    SERVO_HOLD_DEG_PER_S = 45.0


    # 카메라 모듈이 거꾸로 달려 있어 캡처를 180도 회전(hflip+vflip)시켜 쓴다.
    # 그래서 서보를 왼쪽으로 돌리면 화면 속 장면은 반대로 흐른다 — 웹에서 왼쪽
    # 화살표를 눌렀는데 오른쪽으로 도는 것처럼 보였다. 화면(=사용자가 보는 기준)에
    # 맞추기 위해 서보로 나가는 각도만 뒤집는다. 웹/텔레메트리가 쓰는 논리 각도
    # (pan 작을수록 화면상 왼쪽)는 그대로 유지된다.
    PAN_INVERT = True

    def set_ai_overlay_encoder(self, fn):
        """카메라 루프가 30fps 로 AI 오버레이를 만들 때 쓸 인코더를 등록한다.

        fn(bgr_frame) -> jpeg bytes | None. 최근 탐지 결과를 얹어 돌려주면 된다.
        None 을 돌려주면 그 프레임은 건너뛴다.
        """
        self._ai_overlay_encoder = fn

    def _servo_limits(self, channel):
        """서보 채널의 하드웨어 각도 범위. 팬은 반전돼 있어도 범위는 같다."""
        if channel == self.SERVO_TILT:
            return self.TILT_MIN, self.TILT_MAX
        return self.PAN_MIN, self.PAN_MAX

    def set_camera_direction(self, pan_dir=None, tilt_dir=None):
        """화살표를 누르고 있는 동안 그 방향으로 계속 흐르게 한다. 0이면 멈춘다.

        예전에는 웹이 4도씩 120ms 간격으로 목표를 보냈다. 서보는 4도를 7ms 만에
        끝내고 113ms 를 멈춰 있어서 초당 8번 계단을 밟았고, 그게 "뻑뻑하다"는
        느낌이었다. 이제 방향만 받고 로봇이 매 틱 목표를 앞으로 밀어주므로
        서보가 목표에 닿기 전에 다음 목표가 와서 멈추지 않고 흐른다.
        """
        self._ensure_servo_thread()
        if pan_dir is not None:
            # 화면 기준 방향을 하드웨어 방향으로 뒤집는다(PAN_INVERT 와 같은 이유).
            hw = -int(pan_dir) if self.PAN_INVERT else int(pan_dir)
            self._servo_dir[self.SERVO_PAN] = hw
        if tilt_dir is not None:
            self._servo_dir[self.SERVO_TILT] = int(tilt_dir)
        self._servo_wake.set()
        return {"pan": self.cam_pan, "tilt": self.cam_tilt}

    def _write_servo(self, channel, angle):
        """서보 한 채널에 실제로 각도를 보낸다. 값이 그대로면 보내지 않는다."""
        angle = int(round(angle))
        if self._servo_now.get(channel) == angle:
            return
        try:
            with self._i2c_lock:
                self.car.Ctrl_Servo(channel, angle)
            self._servo_now[channel] = angle
        except Exception as e:
            print(f"[RealHAL] 서보 {channel} 제어 실패: {e}")

    def _servo_loop(self):
        """목표 각도까지 촘촘히 좁혀가는 스레드.

        한 틱에 움직일 수 있는 최대치를 정해두고 그만큼만 다가간다. 목표에
        도달하면 이벤트를 기다리며 잠들어 I2C 를 놀린다 — 가만히 있을 때
        불필요한 전송이 나가면 다른 명령과 뒤엉킨다.
        """
        max_step = self.SERVO_DEG_PER_S * self.SERVO_TICK_S
        hold_step = self.SERVO_HOLD_DEG_PER_S * self.SERVO_TICK_S
        while not self._camera_stop.is_set():
            moved = False
            # 방향이 눌려 있으면 목표를 계속 앞으로 밀어준다.
            for channel, direction in list(self._servo_dir.items()):
                if not direction:
                    continue
                lo, hi = self._servo_limits(channel)
                nxt = self._servo_target.get(channel, 90) + direction * hold_step
                self._servo_target[channel] = max(lo, min(hi, nxt))
                if channel == self.SERVO_PAN:
                    hw = self._servo_target[channel]
                    self.cam_pan = (180 - hw) if self.PAN_INVERT else hw
                else:
                    self.cam_tilt = self._servo_target[channel]
                moved = True
            for channel, target in list(self._servo_target.items()):
                now = self._servo_now.get(channel)
                if now is None:
                    self._write_servo(channel, target)
                    moved = True
                    continue
                delta = target - now
                if abs(delta) < 0.5:
                    continue
                if abs(delta) <= self.SERVO_DIRECT_DEG:
                    # 짧은 이동은 서보에게 맡긴다. 자기 곡선이 우리가 만드는
                    # 등속 스텝보다 부드럽다.
                    self._write_servo(channel, target)
                else:
                    # 프리셋 전환처럼 크게 뛸 때만 나눠서 간다. 한 번에 던지면
                    # 서보가 최고 속도로 휘둘러 몸체가 흔들린다.
                    step = max(-max_step, min(max_step, delta))
                    self._write_servo(channel, now + step)
                moved = True
            if moved:
                time.sleep(self.SERVO_TICK_S)
            else:
                # 할 일이 없으면 잠든다. 새 목표가 오면 깨어난다.
                self._servo_wake.wait(0.5)
                self._servo_wake.clear()

    def _ensure_servo_thread(self):
        if self._servo_thread is None or not self._servo_thread.is_alive():
            self._servo_thread = threading.Thread(target=self._servo_loop, daemon=True)
            self._servo_thread.start()

    def set_camera_angle(self, pan=None, tilt=None):
        """카메라 팬/틸트의 '목표' 각도를 정한다. 실제 이동은 서보 스레드가 맡는다.

        pan  = 좌우 (실제 서보 채널은 SERVO_PAN)
        tilt = 상하 (실제 서보 채널은 SERVO_TILT)

        호출은 즉시 돌아온다. 웹이 아무리 자주 불러도 목표만 갱신될 뿐이라
        네트워크 지연이 움직임에 드러나지 않는다.
        """
        self._ensure_servo_thread()
        if pan is not None:
            pan = max(self.PAN_MIN, min(self.PAN_MAX, int(pan)))
            hw_pan = (180 - pan) if self.PAN_INVERT else pan
            self._servo_target[self.SERVO_PAN] = hw_pan
            self.cam_pan = pan
        if tilt is not None:
            tilt = max(self.TILT_MIN, min(self.TILT_MAX, int(tilt)))
            self._servo_target[self.SERVO_TILT] = tilt
            self.cam_tilt = tilt
        self._servo_wake.set()
        return {"pan": self.cam_pan, "tilt": self.cam_tilt}

    def trigger_buzzer(self, duration_sec: float = 1.5):
        """사람 감지(SR-03) 등에서 울리는 경보 부저. 실제 성공 여부를 돌려준다.

        Raspbot의 부저는 BOARD 32번 핀에 물린 패시브 부저라 PWM으로 음을 만들어야
        소리가 난다(Yahboom 공식 데모 `01.Drive buzzer/Buzzer_test.ipynb` 기준, 440Hz).
        YB_Pcb_Car에는 Ctrl_Buzzer가 아예 없다 — 예전 구현이 그걸 부르고 있어서
        AttributeError가 나고, except가 삼킨 뒤에도 웹에는 성공이라고 응답했다.
        """
        if self._buzzer_pwm is None:
            return {"status": "error", "message": "부저를 초기화하지 못했습니다."}

        def _buzz():
            try:
                # 삑-삑-삑 패턴 (0.25초 울리고 0.25초 쉼)
                for _ in range(max(1, int(duration_sec / 0.5))):
                    self._buzzer_pwm.ChangeDutyCycle(BUZZER_DUTY)
                    time.sleep(0.25)
                    self._buzzer_pwm.ChangeDutyCycle(0)
                    time.sleep(0.25)
            except Exception as e:
                print(f"[RealHAL] 부저 제어 실패: {e}")
            finally:
                try:
                    self._buzzer_pwm.ChangeDutyCycle(0)
                except Exception:
                    pass

        threading.Thread(target=_buzz, daemon=True).start()
        return {"status": "ok", "buzzer": True, "duration_sec": duration_sec}

    # ── LED 상태 표시등 (BOARD 38=파랑, BOARD 40=빨강, 단순 ON/OFF) ─────
    # Ctrl_RGB()는 이 보드에 존재하지 않는다. 실제로는 GPIO 2핀짜리 LED만 있다.
    # 조합 가능한 상태: 꺼짐 / 파랑만 / 빨강만 / 파랑+빨강 동시 (보라빛)

    LED_BLUE_PIN = 38
    LED_RED_PIN = 40

    def _init_leds(self):
        """LED 핀 초기화 — __init__에서 호출."""
        try:
            GPIO.setup(self.LED_BLUE_PIN, GPIO.OUT)
            GPIO.setup(self.LED_RED_PIN, GPIO.OUT)
            GPIO.output(self.LED_BLUE_PIN, GPIO.LOW)
            GPIO.output(self.LED_RED_PIN, GPIO.LOW)
        except Exception as e:
            print(f"[RealHAL] LED 초기화 실패: {e}")

    def set_status_led(self, status: str):
        """상태에 따라 LED를 켜고 끈다.
        - 'patrol': 파랑만 (정상 순찰)
        - 'alert': 빨강만 (침입자/긴급)
        - 'manual': 파랑+빨강 (수동 조작)
        - 'off': 전부 끔
        """
        blue = GPIO.LOW
        red = GPIO.LOW
        if status == "patrol":
            blue = GPIO.HIGH
        elif status == "alert":
            red = GPIO.HIGH
        elif status in ("manual", "ai"):
            blue = GPIO.HIGH
            red = GPIO.HIGH
        try:
            GPIO.output(self.LED_BLUE_PIN, blue)
            GPIO.output(self.LED_RED_PIN, red)
        except Exception:
            pass

    def flash_alert_led(self, duration_sec: float = 2.0):
        """빨강 LED 깜빡임 — 침입자 감지 등 긴급 시."""
        def _flash():
            try:
                for _ in range(max(1, int(duration_sec * 3))):
                    GPIO.output(self.LED_RED_PIN, GPIO.HIGH)
                    time.sleep(0.16)
                    GPIO.output(self.LED_RED_PIN, GPIO.LOW)
                    time.sleep(0.16)
            except Exception:
                pass
        threading.Thread(target=_flash, daemon=True).start()

    # ── 부저 멜로디 패턴 ──────────────────────────────────────────────
    # 패시브 부저라 주파수를 바꾸면 다른 음이 난다.
    # 상황별로 다른 소리를 내서 구분할 수 있게 한다.

    def buzz_success(self):
        """짧은 성공음 (QR 스캔 성공 등) — 높은 음 1회."""
        if self._buzzer_pwm is None:
            return
        def _beep():
            try:
                self._buzzer_pwm.ChangeFrequency(880)
                self._buzzer_pwm.ChangeDutyCycle(BUZZER_DUTY)
                time.sleep(0.15)
                self._buzzer_pwm.ChangeDutyCycle(0)
                self._buzzer_pwm.ChangeFrequency(BUZZER_FREQ_HZ)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()

    def buzz_warning(self):
        """경고음 — 중간 음 2회."""
        if self._buzzer_pwm is None:
            return
        def _warn():
            try:
                for _ in range(2):
                    self._buzzer_pwm.ChangeFrequency(660)
                    self._buzzer_pwm.ChangeDutyCycle(BUZZER_DUTY)
                    time.sleep(0.2)
                    self._buzzer_pwm.ChangeDutyCycle(0)
                    time.sleep(0.15)
                self._buzzer_pwm.ChangeFrequency(BUZZER_FREQ_HZ)
            except Exception:
                pass
        threading.Thread(target=_warn, daemon=True).start()

    def buzz_siren(self, duration_sec: float = 3.0):
        """사이렌 패턴 — 고저음 반복 (침입자 경보용)."""
        if self._buzzer_pwm is None:
            return
        def _siren():
            try:
                for _ in range(max(1, int(duration_sec * 2))):
                    self._buzzer_pwm.ChangeFrequency(1000)
                    self._buzzer_pwm.ChangeDutyCycle(BUZZER_DUTY)
                    time.sleep(0.15)
                    self._buzzer_pwm.ChangeFrequency(400)
                    self._buzzer_pwm.ChangeDutyCycle(BUZZER_DUTY)
                    time.sleep(0.15)
                self._buzzer_pwm.ChangeDutyCycle(0)
                self._buzzer_pwm.ChangeFrequency(BUZZER_FREQ_HZ)
            except Exception:
                pass
        threading.Thread(target=_siren, daemon=True).start()

    def cleanup(self):
        """프로그램 종료 시 호출 — 카메라 스레드 정지 + GPIO 핀 정리. controller.py의
        5개 인터페이스에는 없지만, run_real.py의 종료 처리(try/finally)에서만 쓴다."""
        self._camera_stop.set()
        if self._camera_thread is not None:
            self._camera_thread.join(timeout=1.0)
        self.stop()
        if self._picam2 is not None:
            self._picam2.stop()
        if self._buzzer_pwm is not None:
            try:
                self._buzzer_pwm.stop()  # 안 멈추면 종료 후에도 부저가 계속 울린다
            except Exception:
                pass
        GPIO.cleanup()
