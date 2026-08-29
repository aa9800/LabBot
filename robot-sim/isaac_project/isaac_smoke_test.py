"""Isaac Sim + isaac_hal.py + controller.py 연동 스모크 테스트.

omni.usd 환경에서 IsaacHAL을 주입한 PatrolController가 에러 없이 
움직이는지 확인.

controller.py는 파일 이름 그대로 import한다. 
Isaac Sim은 내장 모듈 이름 충돌이 없다. robot-sim/ 루트를
sys.path에 추가해서 controller.py를 그대로 재사용한다.

시나리오: 로봇 전방에 동적 장애물을 등장시켜 정지, 좌우 회전 스캔, 우회,
원래 경로 복귀까지 실제 Isaac 스테이지 좌표에서 확인한다.
"""
import math
import os
import sys

from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

import numpy as np  # noqa: E402
import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from controller import PatrolController  # noqa: E402

from isaac_hal import LAB_TRACK_POINTS_M, IsaacHAL  # noqa: E402
from raspbot_model import KinematicRaspbot, create_raspbot  # noqa: E402

OBSTACLE_PATH = "/World/Obstacle"


def _make_checkpoints():
    # 10초짜리 스모크 테스트 시간 안에 실제로 닿을 수 있는 거리에 하나만 둔다
    # (처음에 트랙 중간(1m 지점)에 뒀다가 speed=70(=0.07m/s)로는 10초 안에 못 닿아서
    # scan 이벤트가 항상 비어있었음 — 시작점에서 0.4m 지점으로 당김).
    x = LAB_TRACK_POINTS_M[0][0] + 0.2
    y = LAB_TRACK_POINTS_M[0][1]
    return [{"name": "체크포인트-A", "x": x, "y": y, "radius": 0.1}]


OBSTACLE_PARKED_XY = (100.0, 100.0)  # 안 쓸 때 치워두는 먼 좌표 — prim 자체는 안 지운다


def _create_obstacle(stage):
    """장애물 prim을 시뮬레이션 시작 전에 미리 한 번만 만든다.

    처음엔 add/remove로 껐다 켰는데, 물리 스텝 도중 스테이지 구조를 바꾸면(prim 생성/삭제)
    Jetbot Articulation의 캐시된 physics view가 깨져서
    `AttributeError: 'Articulation' object has no attribute '_physics_view'`가 났다
    (실제로 겪음, 2026-08-26). 그래서 prim은 미리 만들어두고 "켜고 끄기"는 위치만
    옮기는 방식(멀리 치워두기)으로 바꿨다 — 구조 변경이 아니라 값 변경이라 안전하다.
    """
    prim = stage.DefinePrim(OBSTACLE_PATH, "Cube")
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(OBSTACLE_PARKED_XY[0], OBSTACLE_PARKED_XY[1], 0.05))
    xform.AddScaleOp().Set(Gf.Vec3d(0.05, 0.05, 0.05))
    return translate_op


def _move_obstacle(translate_op, x, y):
    translate_op.Set(Gf.Vec3d(x, y, 0.05))


def _park_obstacle(translate_op):
    translate_op.Set(Gf.Vec3d(OBSTACLE_PARKED_XY[0], OBSTACLE_PARKED_XY[1], 0.05))


def main():
    print("STEP: World()", flush=True)
    world = World(stage_units_in_meters=1.0)
    print("STEP: add_default_ground_plane", flush=True)
    world.scene.add_default_ground_plane()
    stage = omni.usd.get_context().get_stage()
    print("STEP: create project Raspbot", flush=True)
    robot_path = create_raspbot(stage)
    raspbot = KinematicRaspbot(stage, robot_path)
    print("STEP: world.reset()", flush=True)
    world.reset()
    print("STEP: world.reset() done", flush=True)

    # 로봇을 트랙 시작점(코너)에, 다음 코너를 바라보도록 배치
    print("STEP: positioning robot", flush=True)
    start_x, start_y = LAB_TRACK_POINTS_M[0]
    next_x, next_y = LAB_TRACK_POINTS_M[1]
    heading = math.atan2(next_y - start_y, next_x - start_x)
    qz, qw = math.sin(heading / 2), math.cos(heading / 2)
    raspbot.set_world_poses(
        positions=np.array([[start_x, start_y, 0.0]]),
        orientations=np.array([[qw, 0.0, 0.0, qz]]),
    )
    print("STEP: robot positioned", flush=True)

    print("STEP: creating obstacle prim (parked far away)", flush=True)
    obstacle_translate_op = _create_obstacle(stage)
    print("STEP: creating IsaacHAL", flush=True)
    hal = IsaacHAL(stage, raspbot, obstacle_prim_path=OBSTACLE_PATH, checkpoints=_make_checkpoints())
    print("STEP: IsaacHAL created", flush=True)

    events = []
    controller = PatrolController(
        hal,
        on_scan=lambda loc: events.append(("scan", loc)),
        on_obstacle=lambda d: events.append(("obstacle", d)),
        on_obstacle_cleared=lambda: events.append(("cleared", None)),
    )

    dt = 1.0 / 60.0
    print("STEP: entering main loop", flush=True)
    for i in range(900):  # 15초 분량: 전체 우회 동작과 경로 복귀까지 확인
        if i % 100 == 0:
            print(f"STEP: loop i={i}", flush=True)
        if i == 150:  # 2.5초 지점: 장애물 등장 (prim은 이미 있음, 위치만 옮김)
            rx, ry, fx, fy = hal._position_and_heading()
            _move_obstacle(obstacle_translate_op, rx + fx * 0.30, ry + fy * 0.30)

        hal.update_tick_cache()
        controller.tick(dt)
        world.step(render=False)

    print(f"STEP: loop done, events = {events}", flush=True)
    print(f"STEP: avoidance status = {controller.avoidance_status()}", flush=True)
    print(f"STEP: final pose = {hal._position_and_heading()}", flush=True)

    ok_obstacle = any(e[0] == "obstacle" for e in events)
    ok_cleared = any(e[0] == "cleared" for e in events)
    ok_scan = any(e[0] == "scan" for e in events)
    avoidance_result = controller.avoidance_status().get("last_result")
    ok_avoided = avoidance_result == "avoided"

    if ok_obstacle and ok_cleared and ok_avoided:
        print(
            f"ISAAC_CONTROLLER_SMOKE_TEST_OK "
            f"(장애물 감지={ok_obstacle}, 우회={ok_avoided}, 경로복귀={ok_cleared}, 체크포인트 스캔={ok_scan})"
        )
    else:
        raise AssertionError(
            f"ISAAC_CONTROLLER_SMOKE_TEST_FAIL "
            f"(장애물 감지={ok_obstacle}, 우회={ok_avoided}, 경로복귀={ok_cleared}, 체크포인트 스캔={ok_scan})"
        )


if __name__ == "__main__":
    failed = False
    try:
        main()
    except Exception:
        import traceback

        print("STEP: main() raised an exception:", flush=True)
        traceback.print_exc()
        failed = True
    finally:
        simulation_app.close()
    if failed:
        sys.exit(1)
