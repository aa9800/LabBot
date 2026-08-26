"""실제 Raspbot(Raspberry Pi 5 + Yahboom Raspbot)용 HAL.

sim/hal_sim.py, webots_hal.py, isaac_hal.py와 반드시 같은 5개 메서드
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
`not GPIO.input(pin)`으로 뒤집어서 "선 위에 있으면 True"로 SimHAL/WebotsHAL과 의미를 맞춘다.

## set_motion(speed, turn) 변환 방식 (엔지니어링 결정, 실측 아님)

controller.py는 SPEED=70, TURN_GAIN=90 같은 값을 그대로 내려보낸다 — 이 값들은 이미
Yahboom 데모들이 Car_Run(70, 70)처럼 직접 쓰는 0~100 PWM 스케일과 같은 자릿수라서,
Webots/Isaac처럼 m/s로 변환하지 않고 표준 아케이드 믹싱(left = speed - turn,
right = speed + turn)만 적용한 뒤 [-100, 100]으로 클램프한다. 이건 하드웨어 사양이 아니라
이 프로젝트에서 고른 변환 공식이라는 점을 분명히 해둔다.
"""
import math
import threading
import time

import RPi.GPIO as GPIO
import YB_Pcb_Car

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

# ── 카메라/QR ────────────────────────────────────────────────────────
CAMERA_SIZE = (320, 240)


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

        self.car = YB_Pcb_Car.YB_Pcb_Car()
        self.last_speed = 0.0
        self.last_turn = 0.0
        self.cam_pan = 90
        self.cam_tilt = 90
        try:
            self.car.Ctrl_Servo(1, 90)
            self.car.Ctrl_Servo(2, 90)
        except Exception:
            pass

        self._picam2 = None
        self._pyzbar = None
        self._cv2 = None
        self._stream_server = None
        self._latest_frame = None
        self._frame_lock = threading.Lock()
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
            self._picam2 = Picamera2()
            config = self._picam2.create_preview_configuration(
                main={"format": "BGR888", "size": CAMERA_SIZE},
                controls={"FrameDurationLimits": (33333, 33333)}  # 30fps 하드웨어 고정
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

    def _camera_loop(self):
        """항상 돌아가는 카메라 캡처 루프 — capture_array()의 하드웨어 블로킹(33.3ms)에 정확히 동기화된 무진동 30fps."""
        while not self._camera_stop.is_set():
            try:
                frame = self._picam2.capture_array()
                with self._frame_lock:
                    self._latest_frame = frame
                if self._cv2 is not None and self._stream_server is not None:
                    # picamera2의 RGB 출력을 OpenCV가 기대하는 BGR로 변환 (손이 파란색/초록색으로 보이는 스머프 색상 왜곡 해결)
                    bgr_frame = self._cv2.cvtColor(frame, self._cv2.COLOR_RGB2BGR)
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
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

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

    def set_motion(self, speed, turn):
        """아케이드 믹싱(모듈 docstring 참고) 후 클램프해서 Control_Car로 보낸다."""
        self.last_speed = float(speed)
        self.last_turn = float(turn)
        left = speed - turn
        right = speed + turn
        left = max(-MOTOR_SPEED_LIMIT, min(MOTOR_SPEED_LIMIT, left))
        right = max(-MOTOR_SPEED_LIMIT, min(MOTOR_SPEED_LIMIT, right))
        self.car.Control_Car(int(left), int(right))

    def stop(self):
        self.last_speed = 0.0
        self.last_turn = 0.0
        self.car.Car_Stop()

    def set_camera_angle(self, pan=None, tilt=None):
        """카메라 2축 팬/틸트 서보 각도 조절 (0~180도, 중앙 90도).
        Servo 1: Pan (좌우, 0~180도)
        Servo 2: Tilt (상하, 0~180도)
        """
        if pan is not None:
            pan = max(0, min(180, int(pan)))
            try:
                self.car.Ctrl_Servo(1, pan)
            except Exception as e:
                print(f"[RealHAL] Pan 서보 제어 실패: {e}")
            self.cam_pan = pan
        if tilt is not None:
            tilt = max(0, min(180, int(tilt)))
            try:
                self.car.Ctrl_Servo(2, tilt)
            except Exception as e:
                print(f"[RealHAL] Tilt 서보 제어 실패: {e}")
            self.cam_tilt = tilt

    def cleanup(self):
        """프로그램 종료 시 호출 — 카메라 스레드 정지 + GPIO 핀 정리. controller.py의
        5개 인터페이스에는 없지만, run_real.py의 종료 처리(try/finally)에서만 쓴다."""
        self._camera_stop.set()
        if self._camera_thread is not None:
            self._camera_thread.join(timeout=1.0)
        self.stop()
        if self._picam2 is not None:
            self._picam2.stop()
        GPIO.cleanup()
