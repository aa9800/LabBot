"""Real HAL 자리 — Raspbot이 도착하면 여기를 채운다.

sim/hal_sim.py와 메서드 이름·시그니처를 반드시 동일하게 유지해야
controller.py(판단 로직)를 고치지 않고 그대로 재사용할 수 있다.
지금은 하드웨어가 없어서 전부 미구현 상태로만 남겨둔다.
"""


class RealHAL:
    def __init__(self):
        # TODO: Raspbot 초기화 (카메라, GPIO, 모터 드라이버)
        raise NotImplementedError(
            "하드웨어가 준비되면 구현하세요 — sim/hal_sim.py의 메서드 시그니처를 그대로 따르세요."
        )

    def read_line_sensors(self):
        # TODO: 4채널 라인트래킹 센서 GPIO 값을 읽어 [left, mid_left, mid_right, right] bool로 반환
        raise NotImplementedError

    def read_ultrasonic(self):
        # TODO: 초음파 센서 거리값 읽기
        raise NotImplementedError

    def try_read_qr(self):
        # TODO: 카메라 프레임 캡처 -> OpenCV/pyzbar로 QR 디코드. 없으면 None
        raise NotImplementedError

    def set_motion(self, speed, turn):
        # TODO: (speed, turn)을 모터 PWM 값으로 변환해 출력
        raise NotImplementedError

    def stop(self):
        # TODO: 모터 정지
        raise NotImplementedError
