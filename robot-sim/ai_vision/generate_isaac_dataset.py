"""LabBot USD 장면을 실제 렌더링해 YOLO 합성 학습 데이터를 만든다."""
import math
import random
import sys
from pathlib import Path

import cv2
import numpy as np

from isaacsim.simulation_app import SimulationApp

app = SimulationApp({"headless": True, "width": 640, "height": 640})

import omni.usd
from isaacsim.core.api import World
from isaacsim.sensors.camera import Camera
from pxr import Gf, UsdGeom, UsdLux

ROOT = Path(__file__).resolve().parents[1]
ASSET_PATH = ROOT / "isaac_project" / "assets" / "labkeeper_lab_v2.usda"
OUTPUT_ROOT = ROOT / "datasets" / "synthetic_isaac"
IMAGE_SIZE = 640

TARGETS = {
    "microscope": [[
        "/World/MainBench/MicroscopeBase", "/World/MainBench/MicroscopeBody",
        "/World/MainBench/MicroscopeLens", "/World/MainBench/MicroscopeStage",
    ]],
    "centrifuge": [[
        "/World/MainBench/Centrifuge", "/World/MainBench/CentrifugeLid",
        "/World/MainBench/CentrifugeUI",
    ]],
    "pipette": [["/World/MainBench/PipetteStand"] + [f"/World/MainBench/Pipette_{i}" for i in range(6)]],
    "beaker": [[f"/World/MainBench/Beaker_{i}"] for i in range(3)],
    "flask": [[f"/World/MainBench/Flask_{i}"] for i in range(2)],
    "reagent_bottle": [[f"/World/North/Reagent_{row}_{col}"] for row in range(3) for col in range(11)],
    "fire_extinguisher": [["/World/Safety/FireExtinguisher", "/World/Safety/ExtinguisherHandle"]],
    "spill_kit": [["/World/Safety/SpillKit"]],
    "flammable_cabinet": [["/World/Safety/FlammableCabinet"]],
    "biohazard_bin": [["/World/Safety/WasteBin_0"]],
}

OCCLUDER_PATHS = [
    "/World/Architecture",
    "/World/MainBench/IslandWest", "/World/MainBench/IslandEast",
    "/World/MainBench/WestWallBench", "/World/MainBench/EastWallBench",
    "/World/MainBench/WestUpper", "/World/MainBench/EastUpper",
    "/World/North/Reagent_Desk",
]

# 라벨/문이 달린 물체는 정면 쪽에서 촬영해야 실제 카메라 모습과 일치한다.
PREFERRED_ANGLES = {
    "reagent_bottle": -math.pi / 2,
    "fire_extinguisher": -math.pi / 2,
    "spill_kit": -math.pi / 2,
    "flammable_cabinet": -math.pi / 2,
    "biohazard_bin": -math.pi / 2,
}


def look_at_quaternion(eye, target):
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1))
    quat = matrix.GetInverse().ExtractRotation().GetQuat()
    imaginary = quat.GetImaginary()
    return np.array([quat.GetReal(), imaginary[0], imaginary[1], imaginary[2]])


def world_corners(stage, paths):
    cache = UsdGeom.BBoxCache(0.0, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    points = []
    for path in paths:
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid():
            continue
        box = cache.ComputeWorldBound(prim).ComputeAlignedBox()
        low, high = box.GetMin(), box.GetMax()
        for x in (low[0], high[0]):
            for y in (low[1], high[1]):
                for z in (low[2], high[2]):
                    points.append((x, y, z))
    return np.asarray(points, dtype=np.float64)


def save_sample(camera, world, stage, class_id, class_name, paths, index, split):
    corners = world_corners(stage, paths)
    if len(corners) == 0:
        return False
    low, high = corners.min(axis=0), corners.max(axis=0)
    center = (low + high) / 2
    extent = high - low
    radius = max(0.85, float(max(extent)) * random.uniform(3.4, 5.0))
    preferred = PREFERRED_ANGLES.get(class_name)
    angle = random.uniform(0, math.tau) if preferred is None else preferred + random.uniform(-0.55, 0.55)
    eye = np.array([
        center[0] + math.cos(angle) * radius,
        center[1] + math.sin(angle) * radius,
        center[2] + random.uniform(-0.05, 0.45) * max(0.4, extent[2]),
    ])
    aim = center + np.array([
        random.uniform(-0.08, 0.08) * max(extent[0], 0.2),
        random.uniform(-0.08, 0.08) * max(extent[1], 0.2),
        random.uniform(-0.05, 0.08) * max(extent[2], 0.2),
    ])
    # Gf.SetLookAt 결과는 USD 카메라 축(+Y up, -Z forward) 기준이다.
    camera.set_world_pose(
        position=eye,
        orientation=look_at_quaternion(eye, aim),
        camera_axes="usd",
    )
    for _ in range(3):
        world.step(render=True)

    rgba = camera.get_rgba()
    if rgba is None:
        return False
    rgba = np.asarray(rgba)
    if rgba.dtype != np.uint8:
        rgba = np.clip(rgba * 255.0, 0, 255).astype(np.uint8)
    bgr = cv2.cvtColor(rgba[:, :, :4], cv2.COLOR_RGBA2BGR)

    image_points = np.asarray(camera.get_image_coords_from_world_points(corners))
    finite = image_points[np.isfinite(image_points).all(axis=1)]
    if len(finite) < 4:
        return False
    x1, y1 = np.maximum(finite.min(axis=0), 0)
    x2, y2 = np.minimum(finite.max(axis=0), IMAGE_SIZE - 1)
    if x2 - x1 < 12 or y2 - y1 < 12 or x1 >= x2 or y1 >= y2:
        return False

    image_dir = OUTPUT_ROOT / split / "images"
    label_dir = OUTPUT_ROOT / split / "labels"
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    stem = f"isaac_{class_name}_{index:04d}"
    encoded_ok, encoded = cv2.imencode(
        ".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), random.randint(82, 96)]
    )
    if not encoded_ok:
        return False
    (image_dir / f"{stem}.jpg").write_bytes(encoded.tobytes())
    xc, yc = (x1 + x2) / 2 / IMAGE_SIZE, (y1 + y2) / 2 / IMAGE_SIZE
    width, height = (x2 - x1) / IMAGE_SIZE, (y2 - y1) / IMAGE_SIZE
    (label_dir / f"{stem}.txt").write_text(
        f"{class_id} {xc:.6f} {yc:.6f} {width:.6f} {height:.6f}\n", encoding="utf-8"
    )
    return True


def main(samples_per_class=45):
    random.seed(20260827)
    if not ASSET_PATH.exists():
        raise FileNotFoundError(f"먼저 build_lab_asset.py를 실행하세요: {ASSET_PATH}")
    omni.usd.get_context().open_stage(str(ASSET_PATH))
    for _ in range(5):
        app.update()
    stage = omni.usd.get_context().get_stage()
    dome = UsdLux.DomeLight.Define(stage, "/World/SyntheticDomeLight")
    dome.CreateIntensityAttr(1800.0)
    dome.CreateColorAttr(Gf.Vec3f(0.92, 0.97, 1.0))
    sun = UsdLux.DistantLight.Define(stage, "/World/SyntheticSun")
    sun.CreateIntensityAttr(950.0)
    sun.CreateColorAttr(Gf.Vec3f(1.0, 0.95, 0.86))
    UsdGeom.Xformable(sun).AddRotateXOp().Set(-48.0)
    for path in OCCLUDER_PATHS:
        prim = stage.GetPrimAtPath(path)
        if prim.IsValid():
            UsdGeom.Imageable(prim).MakeInvisible()
    world = World(stage_units_in_meters=1.0)
    UsdGeom.Camera.Define(stage, "/World/SyntheticCamera")
    camera = Camera("/World/SyntheticCamera", resolution=(IMAGE_SIZE, IMAGE_SIZE), frequency=30)
    world.scene.add(camera)
    world.reset()
    camera.initialize()

    for class_id, (class_name, target_groups) in enumerate(TARGETS.items()):
        made = 0
        attempts = 0
        while made < samples_per_class and attempts < samples_per_class * 4:
            split = "train" if made < int(samples_per_class * 0.8) else "valid" if made < int(samples_per_class * 0.93) else "test"
            paths = random.choice(target_groups)
            if save_sample(camera, world, stage, class_id, class_name, paths, made, split):
                made += 1
            attempts += 1
        print(f"[Isaac Dataset] {class_name}: {made}/{samples_per_class}")

    # 물품이 없는 연구실 시야를 배경으로 학습해 서랍/벽/가구 오탐을 줄인다.
    for target_groups in TARGETS.values():
        for paths in target_groups:
            for path in paths:
                prim = stage.GetPrimAtPath(path)
                if prim.IsValid():
                    UsdGeom.Imageable(prim).MakeInvisible()
    negative_count = max(60, samples_per_class * 2)
    for index in range(negative_count):
        eye = np.array([random.uniform(-1.6, 1.6), random.uniform(-0.5, 14.0), random.uniform(0.35, 0.65)])
        direction = 1.0 if random.random() > 0.5 else -1.0
        aim = eye + np.array([random.uniform(-0.25, 0.25), direction * 4.0, random.uniform(-0.1, 0.35)])
        camera.set_world_pose(position=eye, orientation=look_at_quaternion(eye, aim), camera_axes="usd")
        for _ in range(2):
            world.step(render=True)
        rgba = np.asarray(camera.get_rgba())
        if rgba.dtype != np.uint8:
            rgba = np.clip(rgba * 255.0, 0, 255).astype(np.uint8)
        bgr = cv2.cvtColor(rgba[:, :, :4], cv2.COLOR_RGBA2BGR)
        ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            continue
        split = "valid" if index % 10 == 8 else "test" if index % 10 == 9 else "train"
        image_dir = OUTPUT_ROOT / split / "images"
        label_dir = OUTPUT_ROOT / split / "labels"
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        stem = f"isaac_background_{index:04d}"
        (image_dir / f"{stem}.jpg").write_bytes(encoded.tobytes())
        (label_dir / f"{stem}.txt").write_text("", encoding="utf-8")
    print(f"[Isaac Dataset] backgrounds: {negative_count}")
    app.close()


if __name__ == "__main__":
    requested = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    main(requested)
