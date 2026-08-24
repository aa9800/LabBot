"""창을 띄우지 않고 로직만 빠르게 확인하는 스크립트.

실행: python check_logic.py
pygame 창 없이 라인트래킹/장애물회피/QR스캔 로직이 정상적으로 도는지만 검증한다.
"""
from controller import PatrolController
from sim.engine import World
from sim.hal_sim import SimHAL

STEP_DT = 1 / 60

# 웹 서버 없이도 체크포인트 로직을 검증하기 위한 가짜 물품 목록(오프라인, 고정값).
FAKE_ITEMS = [
    {"id": 1, "name": "니퍼", "location": "A-1"},
    {"id": 2, "name": "드라이버 세트", "location": "A-1"},
    {"id": 3, "name": "멀티미터", "location": "A-2"},
    {"id": 4, "name": "아두이노 우노", "location": "B-1"},
]


def main():
    world = World(items=FAKE_ITEMS)
    hal = SimHAL(world)
    controller = PatrolController(
        hal,
        on_scan=lambda qr: world.note(f"QR 스캔: {qr}"),
        on_obstacle=lambda d: world.note(f"장애물 감지({d}px)"),
    )

    for i in range(2000):
        if i == 300:
            world.add_obstacle_ahead()
        if i == 600:
            world.clear_obstacles()
        controller.tick(STEP_DT)
        world.robot.step(STEP_DT)

    print(f"최종 위치: ({world.robot.x:.1f}, {world.robot.y:.1f}) heading={world.robot.heading:.1f}")
    print("최근 로그:")
    for line in world.log:
        print(" -", line)


if __name__ == "__main__":
    main()
