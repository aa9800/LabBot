"""LabKeeper 전용 Isaac 장면/4WD/카메라를 짧게 검증하고 PNG를 남긴다."""
import os
import sys

from isaacsim.simulation_app import SimulationApp

simulation_app = SimulationApp({"headless": True, "width": 1440, "height": 810})

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.sensors.camera import Camera  # noqa: E402
from pxr import Gf, UsdLux  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from lab_world import build_lab_environment  # noqa: E402
from raspbot_model import KinematicRaspbot, create_raspbot  # noqa: E402
from render_quality import configure_rtx_quality  # noqa: E402


def _look_at_quaternion(eye, target):
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0.0, 0.0, 1.0))
    quat = matrix.GetInverse().ExtractRotation().GetQuat()
    imag = quat.GetImaginary()
    return np.array([quat.GetReal(), imag[0], imag[1], imag[2]])


def _save_rgb(path, rgba):
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("검증 이미지 인코딩에 실패했습니다.")
    encoded.tofile(path)


def main():
    quality_name, _ = configure_rtx_quality(os.environ.get("LABKEEPER_RENDER_QUALITY", "high"))
    print(f"[LabKeeper smoke] RTX render preset={quality_name}")
    world = World(stage_units_in_meters=1.0)
    stage = omni.usd.get_context().get_stage()
    light = UsdLux.DomeLight.Define(stage, "/World/SmokeDome")
    light.CreateIntensityAttr(680.0)

    build_lab_environment(stage, items=[])
    robot_path = create_raspbot(stage)
    robot = KinematicRaspbot(stage, robot_path)

    camera = Camera("/World/SmokeCamera", resolution=(1440, 810), frequency=30)
    world.scene.add(camera)
    world.reset()
    camera.initialize()
    camera.set_focal_length(1.2)
    camera.set_world_pose(
        position=np.array([13.5, -16.5, 14.5]),
        orientation=_look_at_quaternion((13.5, -16.5, 14.5), (0.0, 3.0, 0.70)),
        camera_axes="usd",
    )
    for _ in range(12):
        world.step(render=True)

    rgba = camera.get_rgba()
    if rgba is None or not np.any(rgba[:, :, :3]):
        raise RuntimeError("렌더 카메라가 비어 있습니다.")
    overview_path = os.path.join(PROJECT_DIR, "lab_scene_smoke.png")
    _save_rgb(overview_path, rgba)

    camera.set_focal_length(2.4)
    camera.set_world_pose(
        position=np.array([0.0, -1.45, 1.62]),
        orientation=_look_at_quaternion((0.0, -1.45, 1.62), (0.0, 8.2, 1.12)),
        camera_axes="usd",
    )
    for _ in range(12):
        world.step(render=True)
    interior = camera.get_rgba()
    interior_path = os.path.join(PROJECT_DIR, "lab_scene_interior.png")
    _save_rgb(interior_path, interior)

    camera.set_focal_length(2.2)
    camera.set_world_pose(
        position=np.array([6.0, -9.25, 3.15]),
        orientation=_look_at_quaternion((6.0, -9.25, 3.15), (0.0, -5.4, 1.00)),
        camera_axes="usd",
    )
    for _ in range(12):
        world.step(render=True)
    rental = camera.get_rgba()
    rental_path = os.path.join(PROJECT_DIR, "lab_scene_rental.png")
    _save_rgb(rental_path, rental)

    camera.set_focal_length(2.2)
    camera.set_world_pose(
        position=np.array([0.20, 8.65, 1.68]),
        orientation=_look_at_quaternion((0.20, 8.65, 1.68), (-4.10, 9.78, 1.24)),
        camera_axes="usd",
    )
    for _ in range(12):
        world.step(render=True)
    partitions = camera.get_rgba()
    partitions_path = os.path.join(PROJECT_DIR, "lab_scene_partitions.png")
    _save_rgb(partitions_path, partitions)

    camera.set_focal_length(2.8)
    camera.set_world_pose(
        position=np.array([0.25, -4.20, 1.78]),
        orientation=_look_at_quaternion((0.25, -4.20, 1.78), (-3.55, -5.55, 1.40)),
        camera_axes="usd",
    )
    for _ in range(18):
        world.step(render=True)
    equipment = camera.get_rgba()
    equipment_path = os.path.join(PROJECT_DIR, "lab_scene_equipment.png")
    _save_rgb(equipment_path, equipment)
    print(
        f"LAB_SCENE_SMOKE_TEST_OK overview={overview_path} interior={interior_path} "
        f"rental={rental_path} partitions={partitions_path} equipment={equipment_path}"
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        simulation_app.close()
