"""Webots가 이 로봇의 controller로 실제 실행하는 진입점 파일.

기존 robot-sim/controller.py(PatrolController)와 notify.py를 복사하거나 고치지
않고, 파일 경로로 직접 불러와서 그대로 재사용한다.

주의 (중요): robot-sim/controller.py의 파일 이름이 정확히 'controller'라서,
Webots가 기본으로 제공하는 'controller' 모듈(Robot, Motor, DistanceSensor 등)과
이름이 겹친다. sys.path에 robot-sim 폴더를 얹으면 이 충돌 때문에 Webots 쪽
'from controller import Robot'가 깨질 수 있다. 그래서 아래처럼 importlib로
파일 경로를 직접 지정해서 불러온다 — sys.path는 절대 건드리지 않는다.
"""
import importlib.util
import os

from controller import Supervisor  # Webots가 기본 제공하는 진짜 controller 모듈
# 장애물 노드의 실제 좌표를 직접 읽어오려면(getFromDef) Robot이 아니라
# Supervisor로 만들어야 한다 — Supervisor는 Robot의 기능을 전부 포함하는 상위 확장판이다.

from webots_hal import WebotsHAL

# .../robot-sim/webots_project/controllers/labkeeper_controller/ 에서 3단계 위 = robot-sim/
_ROBOT_SIM_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def _load_from_path(module_name, relative_path):
    path = os.path.join(_ROBOT_SIM_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_patrol_mod = _load_from_path("labkeeper_patrol_controller", "controller.py")
_notify_mod = _load_from_path("labkeeper_notify", "notify.py")
PatrolController = _patrol_mod.PatrolController

TIME_STEP = 32  # ms — lab.wbt의 basicTimeStep과 맞춘다

# lab.wbt의 체크포인트 표식(CP_A/B/C)과 반드시 같은 좌표로 유지할 것.
CHECKPOINTS = [
    {"name": "선반A", "x": 0.0, "y": -0.5, "radius": 0.1},
    {"name": "선반B", "x": 0.7, "y": 0.0, "radius": 0.1},
    {"name": "선반C", "x": 0.0, "y": 0.5, "radius": 0.1},
]


def main():
    robot = Supervisor()
    hal = WebotsHAL(robot, TIME_STEP, CHECKPOINTS)

    def on_scan(location):
        print(f"[labkeeper] 체크포인트 확인: {location}")

    def on_obstacle(distance):
        print(f"[labkeeper] 장애물 감지({distance:.1f}cm) — 정지 + SR-01 안전이벤트 전송")
        _notify_mod.report_safety_event(
            "SR-01", severity="HIGH", note="Webots 순찰 중 장애물 감지", source="webots-sim"
        )

    def on_obstacle_cleared():
        print("[labkeeper] 장애물 사라짐 — 순찰 재개")

    patrol = PatrolController(
        hal, on_scan=on_scan, on_obstacle=on_obstacle, on_obstacle_cleared=on_obstacle_cleared
    )

    dt = TIME_STEP / 1000.0
    tick_count = 0
    while robot.step(TIME_STEP) != -1:
        patrol.tick(dt)
        tick_count += 1
        if tick_count % 30 == 0:  # 임시 디버그 로그 — 원인 확인되면 지울 것
            print(f"[debug] 전방거리={hal.read_ultrasonic():.1f}cm")


if __name__ == "__main__":
    main()
