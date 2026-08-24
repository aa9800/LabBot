"""Sim HAL — controller.py가 실제로 호출하는 창구.

실제 Raspbot이 도착하면 이 파일과 똑같은 메서드 이름을 가진 real_hal.py로
교체만 하면 controller.py는 한 글자도 안 바꿔도 된다.
"""


class SimHAL:
    def __init__(self, world):
        self.world = world

    def read_line_sensors(self):
        return self.world.robot.line_sensors()

    def read_ultrasonic(self):
        return self.world.robot.ultrasonic(self.world.obstacles)

    def try_read_qr(self):
        """근처 체크포인트의 위치 코드(예: "A-1")를 돌려준다.
        실제 QR 하나가 아니라 '이 선반 구역'을 식별하는 값이라고 보면 된다 —
        어떤 물품이 실제로 거기 있는지는 world.items_at(location)으로 따로 조회한다."""
        marker = self.world.robot.nearby_marker(self.world.markers)
        return marker["location"] if marker else None

    def set_motion(self, speed, turn):
        self.world.robot.speed = speed
        self.world.robot.turn = turn

    def stop(self):
        self.world.robot.speed = 0
        self.world.robot.turn = 0
