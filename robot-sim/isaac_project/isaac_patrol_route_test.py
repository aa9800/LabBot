"""전체 USD 장면에서 Isaac 전용 자동순찰 한 바퀴를 검증한다."""
import math
import os
import sys

os.environ.setdefault("LABKEEPER_SIMREADY_DETAILS", "0")

from isaacsim.simulation_app import SimulationApp

simulation_app = SimulationApp({"headless": True})

import numpy as np  # noqa: E402
import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ROBOT_SIM_ROOT = os.path.dirname(PROJECT_DIR)
sys.path.insert(0, ROBOT_SIM_ROOT)
sys.path.insert(0, PROJECT_DIR)

from isaac_hal import IsaacHAL  # noqa: E402
from lab_world import LAB_TRACK_POINTS_M, build_lab_environment, get_all_checkpoints  # noqa: E402
from raspbot_model import KinematicRaspbot, create_raspbot  # noqa: E402
from waypoint_controller import WaypointPatrolController  # noqa: E402


def main():
    world = World(stage_units_in_meters=1.0)
    stage = omni.usd.get_context().get_stage()
    build_lab_environment(stage, items=[])
    robot = KinematicRaspbot(stage, create_raspbot(stage))
    world.reset()

    start_x, start_y = LAB_TRACK_POINTS_M[0]
    next_x, next_y = LAB_TRACK_POINTS_M[1]
    heading = math.atan2(next_y - start_y, next_x - start_x)
    robot.set_world_poses(
        positions=np.array([[start_x, start_y, 0.0]]),
        orientations=np.array([[math.cos(heading / 2), 0.0, 0.0, math.sin(heading / 2)]]),
    )

    hal = IsaacHAL(
        stage,
        robot,
        obstacle_prim_path="/World/Obstacle",
        checkpoints=get_all_checkpoints(),
    )
    controller = WaypointPatrolController(hal, LAB_TRACK_POINTS_M)
    dt = 1.0 / 60.0

    for tick in range(60 * 300):
        hal.update_tick_cache()
        controller.tick(dt)
        world.step(render=False)
        if controller.completed_laps >= 1:
            break
    else:
        raise AssertionError(
            f"300초 안에 전체 순찰을 완료하지 못했습니다: "
            f"pose={hal._position_and_heading()} patrol={controller.patrol_status()} "
            f"avoidance={controller.avoidance_status()}"
        )

    x, y, _, _ = hal._position_and_heading()
    home_error = math.hypot(x - start_x, y - start_y)
    if home_error > 0.30:
        raise AssertionError(f"순찰 복귀 오차가 큽니다: {home_error:.3f}m")

    print(
        f"ISAAC_PATROL_ROUTE_TEST_OK ticks={tick + 1} "
        f"waypoints={len(LAB_TRACK_POINTS_M)} home_error={home_error:.3f}m"
    )


if __name__ == "__main__":
    failed = False
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        failed = True
    finally:
        simulation_app.close()
    if failed:
        sys.exit(1)
