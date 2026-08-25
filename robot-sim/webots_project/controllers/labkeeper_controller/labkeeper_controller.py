"""Webots가 이 로봇의 controller로 실제 실행하는 진입점 파일.

기존 robot-sim/controller.py(PatrolController)를 복사하거나 고치지 않고, 파일
경로로 직접 불러와서 그대로 재사용한다.

체크포인트는 이제 하드코딩이 아니라, 실제 웹(Supabase)에 등록된 물품들의
location을 기준으로 자동 생성한다 — pygame 버전(sim/engine.py의 build_markers)과
똑같은 방식이다. 물품을 웹에서 새로 등록하면 다음 실행부터 그 위치가 그대로
체크포인트가 된다.

주의 (중요): robot-sim/controller.py의 파일 이름이 정확히 'controller'라서,
Webots가 기본으로 제공하는 'controller' 모듈(Robot, Motor, DistanceSensor 등)과
이름이 겹친다. sys.path에 robot-sim 폴더를 얹으면 이 충돌 때문에 Webots 쪽
'from controller import Robot'가 깨질 수 있다. 그래서 아래처럼 importlib로
파일 경로를 직접 지정해서 불러온다 — sys.path는 절대 건드리지 않는다.
"""
import datetime
import importlib.util
import math
import os

from controller import Supervisor  # Webots가 기본 제공하는 진짜 controller 모듈
# 장애물 노드의 실제 좌표를 직접 읽어오려면(getFromDef) Robot이 아니라
# Supervisor로 만들어야 한다 — Supervisor는 Robot의 기능을 전부 포함하는 상위 확장판이다.

from webots_hal import WebotsHAL, TRACK_POINTS_M

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
_notify_mod = _load_from_path("labkeeper_notify_supabase", "notify_supabase.py")
PatrolController = _patrol_mod.PatrolController

TIME_STEP = 32  # ms — lab.wbt의 basicTimeStep과 맞춘다

# 웹에서 물품을 하나도 못 가져왔을 때(오프라인 등)를 위한 대체 체크포인트.
# lab.wbt의 CP_A/B/C 표식 위치와 같다 — 이건 장식용 참고 표시일 뿐, 실제 체크포인트는
# 아래 _build_checkpoints_from_items()가 실시간 DB 기준으로 새로 계산한다.
FALLBACK_CHECKPOINTS = [
    {"name": "선반A", "x": 0.0, "y": -0.5, "radius": 0.1},
    {"name": "선반B", "x": 0.7, "y": 0.0, "radius": 0.1},
    {"name": "선반C", "x": 0.0, "y": 0.5, "radius": 0.1},
]


def _point_at_fraction(points, frac):
    """트랙 전체 길이의 frac(0~1) 지점 좌표 — pygame 버전(sim/engine.py)과 같은 계산."""
    total = sum(
        math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        for i in range(len(points) - 1)
    )
    target = total * (frac % 1.0)
    acc = 0.0
    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        seg = math.hypot(bx - ax, by - ay)
        if acc + seg >= target:
            t = (target - acc) / seg if seg else 0
            return (ax + (bx - ax) * t, ay + (by - ay) * t)
        acc += seg
    return points[-1]


def _build_checkpoints_from_items(items):
    """물품들의 location을 모아 중복 제거하고, 트랙 위에 균등하게 체크포인트로 배치한다."""
    locations = sorted({it["location"] for it in items if it.get("location")})
    n = len(locations)
    if n == 0:
        return []
    checkpoints = []
    for i, loc in enumerate(locations):
        x, y = _point_at_fraction(TRACK_POINTS_M, (i + 0.5) / n)
        checkpoints.append({"name": loc, "x": x, "y": y, "radius": 0.12})
    return checkpoints


SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "_last_camera.jpg")
COMMAND_POLL_EVERY = 10   # 몇 틱마다 웹의 원격조작 명령을 확인할지 (너무 자주 물어보면 느려짐)
CAMERA_UPLOAD_EVERY = 30  # 몇 틱마다 카메라 사진을 올릴지 (네트워크 요청이라 더 드물게)
MANUAL_COMMAND_MAX_AGE_SECONDS = 3.0  # 이보다 오래된 수동조작 명령은 "연결 끊김"으로 보고 무조건 정지


def _command_age_seconds(command):
    """robot_commands.updated_at이 지금으로부터 몇 초 전인지. 못 읽으면 아주 큰 값을 돌려줘서
    안전하게(정지 쪽으로) 처리되게 한다 — 관리자가 원격조작 버튼을 누른 뒤 인터넷이 끊기거나
    웹을 닫아버려도, 로봇이 마지막 명령대로 계속 움직이는 사고를 막기 위한 장치다."""
    updated_at = command.get("updated_at")
    if not updated_at:
        return float("inf")
    try:
        ts = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - ts).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def main():
    robot = Supervisor()

    items = _notify_mod.fetch_items()
    checkpoints = _build_checkpoints_from_items(items)
    if checkpoints:
        print(f"[labkeeper] 웹 DB에서 위치 {len(checkpoints)}곳을 체크포인트로 불러왔습니다: "
              f"{[c['name'] for c in checkpoints]}")
    else:
        print("[labkeeper] 웹에서 물품을 못 가져와서 기본 체크포인트(선반A/B/C)로 시작합니다.")
        checkpoints = FALLBACK_CHECKPOINTS

    hal = WebotsHAL(robot, TIME_STEP, checkpoints)

    camera = robot.getDevice("camera")
    camera.enable(TIME_STEP)

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
    tick = 0
    command = {"mode": "auto", "speed": 0.0, "turn": 0.0}
    was_manual = False

    while robot.step(TIME_STEP) != -1:
        tick += 1

        # 웹 Robot Console에서 "수동조작"으로 바꿨는지 주기적으로 확인한다.
        if tick % COMMAND_POLL_EVERY == 0:
            command = _notify_mod.fetch_robot_command()
            is_manual = command.get("mode") == "manual"
            if is_manual != was_manual:
                print(f"[labkeeper] 모드 전환: {'수동조작' if is_manual else '자동순찰'}")
            was_manual = is_manual

        if command.get("mode") == "manual":
            # 원격조작 중에도 안전정지는 그대로 최우선으로 적용한다 —
            # 관리자가 잘못 조작해도 장애물 앞에서는 로봇이 스스로 멈춘다.
            distance = hal.read_ultrasonic()
            stale = _command_age_seconds(command) > MANUAL_COMMAND_MAX_AGE_SECONDS
            if stale:
                hal.stop()  # dead-man switch: 명령이 오래됐다 = 연결이 끊겼다고 보고 정지
            elif distance < _patrol_mod.OBSTACLE_STOP_DISTANCE:
                hal.stop()
            else:
                hal.set_motion(command.get("speed", 0.0), command.get("turn", 0.0))
        else:
            patrol.tick(dt)

        if tick % CAMERA_UPLOAD_EVERY == 0:
            camera.saveImage(SNAPSHOT_PATH, 80)
            _notify_mod.upload_camera_snapshot(SNAPSHOT_PATH)


if __name__ == "__main__":
    main()
