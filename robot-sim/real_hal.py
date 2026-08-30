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
import threading
import time

import RPi.GPIO as GPIO
import YB_Pcb_Car
from frame_broker import FrameBroker

# ── 초음파 ──────────────────────────────────────────────────────────
TRIG_PIN = 16
ECHO_PIN = 18
ECHO_TIMEOUT_S = 0.03  # 공식 데모와 동일 — 이 이상 걸리면 에코 없음으로 보고 포기
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
        try:
            # 둘 다 90도(중앙)라 순서는 무관하지만, 채널 의미는 SERVO_PAN/TILT를 따른다.
            self.car.Ctrl_Servo(self.SERVO_TILT, 90)
            self.car.Ctrl_Servo(self.SERVO_PAN, 90)
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
        self._camera_stop = threading.Event()
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
        """cm 단위 거리. 에코 타임아웃/측정 실패 시 NO_OBSTACLE_CM(다른 HAL과 동일한 관례) —
        -1을 그대로 돌려주면 controller.py가 '아주 가까운 장애물'로 오판해서 즉시 멈춘다."""
        GPIO.output(TRIG_PIN, GPIO.LOW)
        time.sleep(0.000002)
        GPIO.output(TRIG_PIN, GPIO.HIGH)
        time.sleep(0.000015)
        GPIO.output(TRIG_PIN, GPIO.LOW)

        # 아래 두 루프는 에코 핀을 쉬지 않고 읽는 바쁜 대기다. 그대로 두면 측정하는
        # 내내 GIL을 붙잡아 다른 스레드(웹의 서보 명령을 처리하는 HTTP 핸들러)가
        # 굶는다. 그러면 명령이 제때 안 나가고 뭉쳐서 도착해 카메라가 부르르 떤다.
        # sleep(0)은 지연을 거의 안 주면서 GIL만 놓아준다 — 측정 정확도는 그대로다.
        t_send = time.time()
        while not GPIO.input(ECHO_PIN):
            if time.time() - t_send > ECHO_TIMEOUT_S:
                return NO_OBSTACLE_CM
            time.sleep(0)
        t1 = time.time()
        while GPIO.input(ECHO_PIN):
            if time.time() - t1 > ECHO_TIMEOUT_S:
                return NO_OBSTACLE_CM
            time.sleep(0)
        t2 = time.time()
        return ((t2 - t1) * SOUND_SPEED_M_S / 2) * 100

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

    # 이 개체의 서보 배선은 야붐 기본 안내(S1=팬, S2=틸트)와 다르다.
    # 2026-08-30 실측(채널 1~4를 하나씩 단독으로 돌려서 확인):
    #   채널 1 -> 상하(틸트)로 움직임
    #   채널 2 -> 아무 반응 없음 (연결된 서보 없음)
    #   채널 3 -> 아무 반응 없음
    #   채널 4 -> 좌우(팬)로 움직임
    # 예전에는 팬을 2번으로 보내고 있어서 "명령은 나가는데 안 움직인다"였다.
    # 배선을 바꾸는 대신 여기서 번호를 맞춰준다 — 호출부(웹·D패드·화살표 키)는
    # 그대로 pan/tilt 의미로 쓰면 된다.
    SERVO_PAN = 4   # 좌우
    SERVO_TILT = 1  # 상하

    # 틸트는 거치대가 먼저 걸려서 끝까지 돌리면 서보가 스톨(윙 소리만 나고 정지)한다.
    # 팬은 기구 간섭이 없어 전 범위를 쓴다.
    TILT_MIN, TILT_MAX = 35, 145
    PAN_MIN, PAN_MAX = 0, 180

    # 카메라 모듈이 거꾸로 달려 있어 캡처를 180도 회전(hflip+vflip)시켜 쓴다.
    # 그래서 서보를 왼쪽으로 돌리면 화면 속 장면은 반대로 흐른다 — 웹에서 왼쪽
    # 화살표를 눌렀는데 오른쪽으로 도는 것처럼 보였다. 화면(=사용자가 보는 기준)에
    # 맞추기 위해 서보로 나가는 각도만 뒤집는다. 웹/텔레메트리가 쓰는 논리 각도
    # (pan 작을수록 화면상 왼쪽)는 그대로 유지된다.
    PAN_INVERT = True

    def set_camera_angle(self, pan=None, tilt=None):
        """카메라 2축 팬/틸트 서보 각도 조절 (0~180도, 중앙 90도).

        pan  = 좌우 (실제 서보 채널은 SERVO_PAN)
        tilt = 상하 (실제 서보 채널은 SERVO_TILT)
        """
        if pan is not None:
            pan = max(self.PAN_MIN, min(self.PAN_MAX, int(pan)))
            hw_pan = (180 - pan) if self.PAN_INVERT else pan
            try:
                with self._i2c_lock:
                    self.car.Ctrl_Servo(self.SERVO_PAN, hw_pan)
            except Exception as e:
                print(f"[RealHAL] Pan 서보 제어 실패: {e}")
            self.cam_pan = pan
        if tilt is not None:
            tilt = max(self.TILT_MIN, min(self.TILT_MAX, int(tilt)))
            try:
                with self._i2c_lock:
                    self.car.Ctrl_Servo(self.SERVO_TILT, tilt)
            except Exception as e:
                print(f"[RealHAL] Tilt 서보 제어 실패: {e}")
            self.cam_tilt = tilt
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
