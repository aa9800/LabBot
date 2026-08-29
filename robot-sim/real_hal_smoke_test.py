"""real_hal.py의 순수 계산 로직(모터 믹싱/클램프, 초음파 공식)을 로봇 없이 검증한다.

RPi.GPIO / YB_Pcb_Car / picamera2 / libcamera / pyzbar는 실제 Raspbot에만 있는
라이브러리라 개발 PC에는 없다. smoke_test.py가 urllib.request.urlopen을 가짜로
바꿔서 네트워크 없이 notify_supabase.py를 검증하는 것과 같은 방식으로, 여기서는
sys.modules에 가짜(mock) 모듈을 등록해서 real_hal.py를 임포트만이라도 가능하게
만들고 set_motion()의 믹싱·클램프 계산이 맞는지 확인한다.

GPIO 핀 읽기/쓰기, 초음파 타이밍, 카메라 캡처처럼 진짜 하드웨어가 있어야만 의미있는
부분은 여기서 검증하지 않는다 — 그건 로봇 위에서 사람이 지켜보며 확인해야 한다.
"""
import sys
import types

# Windows 콘솔(cp949 등)에서 이 파일의 한글 특수문자(—)가 UnicodeEncodeError를 내는 걸
# 막는다 — smoke_test.py와 같은 이유, 실제 로직과는 무관한 터미널 출력 인코딩 문제.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def _install_fake_hardware_modules():
    """real_hal.py가 import하는 라즈베리파이 전용 모듈들을 가짜로 등록한다."""

    class FakeGPIO(types.ModuleType):
        BOARD = "BOARD"
        IN = "IN"
        OUT = "OUT"
        HIGH = 1
        LOW = 0

        def __init__(self):
            super().__init__("RPi.GPIO")
            self._input_values = {}

        def setwarnings(self, *_a, **_kw):
            pass

        def setmode(self, *_a, **_kw):
            pass

        def setup(self, *_a, **_kw):
            pass

        def output(self, *_a, **_kw):
            pass

        def input(self, pin):
            # 기본값 1(HIGH) = "선 감지 안 됨" — real_hal.py는 이걸 not으로 뒤집는다.
            return self._input_values.get(pin, 1)

        def cleanup(self, *_a, **_kw):
            pass

    fake_gpio = FakeGPIO()
    fake_rpi = types.ModuleType("RPi")
    fake_rpi.GPIO = fake_gpio
    sys.modules["RPi"] = fake_rpi
    sys.modules["RPi.GPIO"] = fake_gpio

    calls = {"control_car": []}

    class FakeCar:
        def Control_Car(self, s1, s2):
            calls["control_car"].append((s1, s2))

        def Car_Stop(self):
            calls["control_car"].append("stop")

    fake_ybcar = types.ModuleType("YB_Pcb_Car")
    fake_ybcar.YB_Pcb_Car = FakeCar
    sys.modules["YB_Pcb_Car"] = fake_ybcar

    # picamera2/libcamera/pyzbar는 enable_camera=False로 테스트하므로 import만 되면 된다.
    fake_picamera2 = types.ModuleType("picamera2")
    fake_picamera2.Picamera2 = object
    sys.modules["picamera2"] = fake_picamera2
    sys.modules["libcamera"] = types.ModuleType("libcamera")
    fake_pyzbar_pkg = types.ModuleType("pyzbar")
    fake_pyzbar_mod = types.ModuleType("pyzbar.pyzbar")
    fake_pyzbar_mod.decode = lambda *_a, **_kw: []
    fake_pyzbar_pkg.pyzbar = fake_pyzbar_mod
    sys.modules["pyzbar"] = fake_pyzbar_pkg
    sys.modules["pyzbar.pyzbar"] = fake_pyzbar_mod

    return calls


def main():
    calls = _install_fake_hardware_modules()
    import real_hal  # noqa: E402  (가짜 모듈 등록 이후에 임포트해야 함)

    hal = real_hal.RealHAL(enable_camera=False)

    # 1) 직진: speed=70, turn=0 -> 양쪽 다 70
    hal.set_motion(70, 0)
    assert calls["control_car"][-1] == (70, 70), calls["control_car"][-1]

    # 2) 우회전(turn 양수): 왼쪽 바퀴를 빠르게, 오른쪽 바퀴를 느리게 돌린다.
    # controller.py/IsaacHAL의 공통 계약(turn < 0 좌회전, turn > 0 우회전)과 같다.
    hal.set_motion(70, 90)
    left, right = calls["control_car"][-1]
    assert left == real_hal.MOTOR_SPEED_LIMIT, (left, right)
    assert right == -20, (left, right)

    # 3) 클램프 상한: 큰 speed+turn도 100을 절대 안 넘는다
    hal.set_motion(100, 100)
    left, right = calls["control_car"][-1]
    assert -100 <= left <= 100 and -100 <= right <= 100, (left, right)

    # 4) 정지
    hal.stop()
    assert calls["control_car"][-1] == "stop"
    assert hal.last_speed == 0.0 and hal.last_turn == 0.0

    # 5) 라인센서 인터페이스 모양만 확인(기본 GPIO 입력=1=HIGH=선 없음 -> 전부 False)
    sensors = hal.read_line_sensors()
    assert sensors == (False, False, False, False), sensors

    # 6) 초음파: 가짜 GPIO는 ECHO_PIN이 항상 1(HIGH)이라 "while not GPIO.input" 루프를
    #    바로 통과하고 "while GPIO.input" 루프에서 타임아웃 -> NO_OBSTACLE_CM이어야 한다.
    distance = hal.read_ultrasonic()
    assert distance == real_hal.NO_OBSTACLE_CM, distance

    # 7) 카메라가 꺼진 테스트 환경에서는 사람으로 오인하지 않고 일반 물체로 분류한다.
    assert hal.classify_obstacle() == "object"

    print("REAL_HAL_SMOKE_TEST_OK — 모터 믹싱/클램프/정지/인터페이스 형태 전부 통과")


if __name__ == "__main__":
    main()
