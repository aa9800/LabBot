"""Isaac Sim이 실제로 실행하는 진입점 — LabKeeper 웹(Supabase)과 연결된 버전.

isaac_smoke_test.py(2단계: controller.py+IsaacHAL 통합 검증, 이미 성공)에 이어, 이제
labkeeper_controller.py(Webots)와 같은 구조로 웹 연동까지 붙인다:

    controller.py (그대로, 수정 없음)
            │
            ├─ sim/hal_sim.py                                   pygame용 (단위테스트)
            ├─ webots_project/.../webots_hal.py                 Webots용 (기존 주 개발·발표)
            └─ isaac_project/isaac_hal.py                       Isaac Sim용 (이 파일이 진입점)

notify_supabase.py도 손대지 않고 그대로 재사용한다 — Webots/pygame/실물이 전부 같은
Supabase 접속 코드를 쓰는 것과 같은 원칙.

실행 (이 PC의 Isaac Sim venv에서):
    C:\\Users\\a9800\\isaac_clean\\venv\\Scripts\\python.exe run_isaac.py

기본은 창을 띄운다(headless 아님) — 발표/개발용으로 눈으로 보면서 확인하기 위해서다.
헤드리스로 돌리려면 환경변수 LABKEEPER_ISAAC_HEADLESS=1.
"""
import datetime
import math
import os
import sys

os.environ.setdefault("LABKEEPER_ISAAC_HEADLESS", "0")
_HEADLESS = os.environ.get("LABKEEPER_ISAAC_HEADLESS", "0") == "1"

from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": _HEADLESS})

import numpy as np  # noqa: E402
import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402
from isaacsim.storage.native import get_assets_root_path  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402

_ROBOT_SIM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROBOT_SIM_ROOT)
from controller import PatrolController, OBSTACLE_STOP_DISTANCE  # noqa: E402
from notify_supabase import (  # noqa: E402
    fetch_items,
    fetch_robot_command,
    is_configured,
    report_safety_event,
)
from run_logger import JsonlRunLogger  # noqa: E402

from isaac_hal import TRACK_POINTS_M, IsaacHAL  # noqa: E402

OBSTACLE_PATH = "/World/Obstacle"
OBSTACLE_PARKED_XY = (100.0, 100.0)  # prim은 유지하고 멀리 치워두는 방식(구조변경 회피)

TIME_STEP_S = 1.0 / 60.0
COMMAND_POLL_EVERY = 30   # 약 0.5초마다 웹의 원격조작 명령 확인
CAMERA_UPLOAD_EVERY = -1  # Isaac 기본 Jetbot엔 아직 카메라 센서를 안 붙여서 비활성(-1)
TELEMETRY_LOG_EVERY = 60  # 약 1초마다 텔레메트리 기록
MANUAL_COMMAND_MAX_AGE_SECONDS = 3.0  # Webots/실물과 동일한 dead-man switch 기준

# 웹에서 물품을 하나도 못 가져왔을 때(오프라인 등)를 위한 대체 체크포인트 — Isaac의
# 작은 테스트 트랙(TRACK_POINTS_M) 위에 이름만 다르게 둔 것. 실제 연구실 배치가 아니라
# controller.py 판단 로직이 웹 연동 없이도 동작하는지 확인하는 최소 구성이다.
FALLBACK_CHECKPOINTS = [
    {"name": "체크포인트-A", "x": TRACK_POINTS_M[0][0] + 0.2, "y": TRACK_POINTS_M[0][1], "radius": 0.1},
]


def _point_at_fraction(points, frac):
    """트랙 전체 길이의 frac(0~1) 지점 좌표 — labkeeper_controller.py(Webots)와 같은 계산."""
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
    """물품들의 location을 모아 중복 제거하고, 트랙 위에 균등 배치한다.

    Isaac 트랙이 작아서(TRACK_POINTS_M, 약 2m x 1.2m) 실제 웹 위치가 여러 개면 체크포인트가
    서로 너무 가까워질 수 있다 — 지금은 판단 로직 연동 검증이 목적이라 그대로 두고,
    실제 연구실 규모 트랙으로 바꿀 때(Webots처럼) 재조정한다."""
    locations = sorted({it["location"] for it in items if it.get("location")})
    n = len(locations)
    if n == 0:
        return []
    checkpoints = []
    for i, loc in enumerate(locations):
        x, y = _point_at_fraction(TRACK_POINTS_M, (i + 0.5) / n)
        checkpoints.append({"name": loc, "x": x, "y": y, "radius": 0.1})
    return checkpoints


def _command_age_seconds(command):
    """labkeeper_controller.py(Webots)와 동일한 로직."""
    updated_at = command.get("updated_at")
    if not updated_at:
        return float("inf")
    try:
        ts = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - ts).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def _create_obstacle(stage):
    prim = stage.DefinePrim(OBSTACLE_PATH, "Cube")
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(OBSTACLE_PARKED_XY[0], OBSTACLE_PARKED_XY[1], 0.05))
    xform.AddScaleOp().Set(Gf.Vec3d(0.05, 0.05, 0.05))
    return translate_op


def main():
    log_dir = os.path.join(_ROBOT_SIM_ROOT, "logs")
    run_log = JsonlRunLogger(log_dir, source="isaac")
    print(f"[labkeeper] 주행 로그: {run_log.path}")

    items = fetch_items()
    checkpoints = _build_checkpoints_from_items(items)
    if checkpoints:
        print(f"[labkeeper] 웹 DB에서 위치 {len(checkpoints)}곳을 체크포인트로 불러왔습니다: "
              f"{[c['name'] for c in checkpoints]}")
    elif not is_configured():
        print("[labkeeper] robot-sim/.env 미설정 — 기본 체크포인트(체크포인트-A)로 시작합니다.")
        checkpoints = FALLBACK_CHECKPOINTS
    else:
        print("[labkeeper] 웹에서 물품을 못 가져와서 기본 체크포인트로 시작합니다.")
        checkpoints = FALLBACK_CHECKPOINTS

    assets_root = get_assets_root_path()
    jetbot_usd = assets_root + "/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd"

    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()
    add_reference_to_stage(usd_path=jetbot_usd, prim_path="/World/Jetbot")
    jetbot = Articulation(prim_paths_expr="/World/Jetbot", name="jetbot")
    world.scene.add(jetbot)
    world.reset()

    start_x, start_y = TRACK_POINTS_M[0]
    next_x, next_y = TRACK_POINTS_M[1]
    heading = math.atan2(next_y - start_y, next_x - start_x)
    qz, qw = math.sin(heading / 2), math.cos(heading / 2)
    jetbot.set_world_poses(
        positions=np.array([[start_x, start_y, 0.0]]),
        orientations=np.array([[qw, 0.0, 0.0, qz]]),
    )

    stage = omni.usd.get_context().get_stage()
    _create_obstacle(stage)  # 장애물 prim은 항상 존재, 실제 등장은 웹에서 조작할 다음 단계용 자리
    hal = IsaacHAL(stage, jetbot, obstacle_prim_path=OBSTACLE_PATH, checkpoints=checkpoints)

    def on_scan(location):
        items_here = [it for it in items if it.get("location") == location]
        names = ", ".join(it["name"] for it in items_here) if items_here else "(등록된 물품 없음)"
        print(f"[labkeeper] 체크포인트 확인: {location} — {names}")
        run_log.write("checkpoint_scanned", checkpoint=location)

    def on_obstacle(distance):
        print(f"[labkeeper] 장애물 감지({distance:.1f}cm) — 정지 + SR-01 안전이벤트 전송")
        run_log.write("obstacle_detected", distance_cm=round(distance, 2), rule_id="SR-01")
        report_safety_event(
            "SR-01", severity="MEDIUM", note="Isaac Sim 순찰 중 장애물 감지", source="isaac-sim"
        )

    def on_obstacle_cleared():
        print("[labkeeper] 장애물 사라짐 — 순찰 재개")
        run_log.write("obstacle_cleared")

    controller = PatrolController(
        hal, on_scan=on_scan, on_obstacle=on_obstacle, on_obstacle_cleared=on_obstacle_cleared
    )

    tick = 0
    command = {"mode": "auto", "speed": 0.0, "turn": 0.0}
    was_manual = False

    print("[labkeeper] 순찰 시작 — 창을 닫거나 Ctrl+C로 종료")
    try:
        while simulation_app.is_running():
            tick += 1

            if tick % COMMAND_POLL_EVERY == 0:
                command = fetch_robot_command()
                is_manual = command.get("mode") == "manual"
                if is_manual != was_manual:
                    print(f"[labkeeper] 모드 전환: {'수동조작' if is_manual else '자동순찰'}")
                    run_log.write("mode_changed", mode="manual" if is_manual else "auto")
                was_manual = is_manual

            if command.get("mode") == "manual":
                distance = hal.read_ultrasonic()
                stale = _command_age_seconds(command) > MANUAL_COMMAND_MAX_AGE_SECONDS
                if stale:
                    hal.stop()  # dead-man switch
                elif distance < OBSTACLE_STOP_DISTANCE:
                    hal.stop()
                else:
                    hal.set_motion(command.get("speed", 0.0), command.get("turn", 0.0))
            else:
                controller.tick(TIME_STEP_S)

            world.step(render=not _HEADLESS)

            if tick % TELEMETRY_LOG_EVERY == 0:
                run_log.write(
                    "telemetry",
                    sim_time_s=round(tick * TIME_STEP_S, 3),
                    mode=command.get("mode", "auto"),
                    command_speed=hal.last_speed,
                    command_turn=hal.last_turn,
                    obstacle_cm=round(hal.read_ultrasonic(), 2),
                )
    except KeyboardInterrupt:
        print("[labkeeper] Ctrl+C — 종료합니다")
    finally:
        run_log.close()
        simulation_app.close()


if __name__ == "__main__":
    main()
