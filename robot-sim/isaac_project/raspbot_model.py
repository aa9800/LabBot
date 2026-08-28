"""Yahboom Raspbot에 맞춘 경량 4WD Isaac Sim 모델 생성기.

외형용 JetBot을 최종 로봇으로 쓰지 않고, 실측 바퀴 지름/트랙 폭과
4륜 스키드 스티어 구성을 반영한다. 정확하지 않은 차체 치수는
robot_spec.json에서 한 곳만 수정하면 된다.
"""
import json
import os

import numpy as np
from pxr import Gf, UsdGeom


_SPEC_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "robot_spec.json")


def load_robot_spec():
    with open(_SPEC_PATH, "r", encoding="utf-8") as stream:
        return json.load(stream)


def _cube(stage, path, position, scale, color, collision=False):
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    xform = UsdGeom.Xformable(cube)
    xform.AddTranslateOp().Set(Gf.Vec3d(*position))
    xform.AddScaleOp().Set(Gf.Vec3f(*scale))
    return cube.GetPrim()


def _wheel(stage, root_path, name, position, radius):
    path = f"{root_path}/{name}"
    wheel = UsdGeom.Cylinder.Define(stage, path)
    wheel.CreateAxisAttr("Y")
    wheel.CreateRadiusAttr(radius)
    wheel.CreateHeightAttr(0.026)
    wheel.CreateDisplayColorAttr([Gf.Vec3f(0.035, 0.04, 0.045)])
    UsdGeom.Xformable(wheel).AddTranslateOp().Set(Gf.Vec3d(*position))
    return path


class KinematicRaspbot:
    """PhysX 마찰 편차 없이 4륜 외형과 차체 포즈를 빠르게 동기화하는 래퍼."""
    is_kinematic = True

    def __init__(self, stage, prim_path):
        self.stage = stage
        self.prim_path = prim_path
        self.dof_names = [
            "left_front_wheel_joint",
            "left_rear_wheel_joint",
            "right_front_wheel_joint",
            "right_rear_wheel_joint",
        ]
        root_xform = UsdGeom.Xformable(stage.GetPrimAtPath(prim_path))
        root_xform.ClearXformOpOrder()
        self._translate_op = root_xform.AddTranslateOp()
        self._orient_op = root_xform.AddOrientOp()
        self._position = np.array([0.0, 0.0, 0.0], dtype=float)
        self._orientation = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)
        self._wheel_angles = np.zeros(4, dtype=float)
        self._wheel_rotate_ops = []
        for name in ("left_front_wheel", "left_rear_wheel", "right_front_wheel", "right_rear_wheel"):
            self._wheel_rotate_ops.append(UsdGeom.Xformable(stage.GetPrimAtPath(f"{prim_path}/{name}")).AddRotateYOp())

    def get_world_poses(self):
        return self._position.reshape(1, 3).copy(), self._orientation.reshape(1, 4).copy()

    def set_world_poses(self, positions=None, orientations=None):
        if positions is not None:
            self._position = np.asarray(positions[0], dtype=float)
            self._translate_op.Set(Gf.Vec3d(*self._position))
        if orientations is not None:
            self._orientation = np.asarray(orientations[0], dtype=float)
            w, x, y, z = self._orientation
            self._orient_op.Set(Gf.Quatf(float(w), Gf.Vec3f(float(x), float(y), float(z))))

    def set_joint_velocities(self, velocities):
        wheel_speeds = np.asarray(velocities[0], dtype=float)
        self._wheel_angles = (self._wheel_angles + np.degrees(wheel_speeds) / 60.0) % 360.0
        for op, angle in zip(self._wheel_rotate_ops, self._wheel_angles):
            op.Set(float(angle))


def create_raspbot(stage, prim_path="/World/Raspbot"):
    """4개 휠 조인트를 가진 Raspbot articulation을 만들고 루트 경로를 반환한다."""
    spec = load_robot_spec()
    dims = spec["dimensionsM"]
    drive = spec["drive"]
    camera = spec["camera"]
    ultrasonic = spec["ultrasonic"]

    length = float(dims["length"])
    width = float(dims["width"])
    height = float(dims["height"])
    wheel_radius = float(drive["wheelRadiusM"])
    track_width = float(drive["trackWidthM"])
    wheel_base = float(drive["wheelBaseM"])

    root = stage.DefinePrim(prim_path, "Xform")

    chassis_center_z = wheel_radius + height * 0.32
    chassis_path = f"{prim_path}/Chassis"
    chassis = stage.DefinePrim(chassis_path, "Xform")
    UsdGeom.Xformable(chassis).AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, chassis_center_z))
    _cube(
        stage,
        f"{chassis_path}/Body",
        (0.0, 0.0, 0.0),
        (length, width, height * 0.45),
        (0.08, 0.32, 0.52),
        collision=True,
    )
    _cube(
        stage,
        f"{chassis_path}/PiDeck",
        (-0.015, 0.0, wheel_radius + height * 0.72 - chassis_center_z),
        (length * 0.72, width * 0.72, height * 0.08),
        (0.12, 0.55, 0.25),
    )
    _cube(
        stage,
        f"{chassis_path}/CameraMast",
        (camera["forwardOffsetM"], 0.0, camera["heightM"] * 0.72 - chassis_center_z),
        (0.018, 0.018, camera["heightM"] * 0.42),
        (0.12, 0.12, 0.14),
    )
    _cube(
        stage,
        f"{chassis_path}/CameraHead",
        (camera["forwardOffsetM"], 0.0, camera["heightM"] - chassis_center_z),
        (0.035, 0.05, 0.026),
        (0.04, 0.04, 0.05),
    )
    _cube(
        stage,
        f"{chassis_path}/Ultrasonic",
        (ultrasonic["forwardOffsetM"], 0.0, ultrasonic["heightM"] - chassis_center_z),
        (0.012, 0.05, 0.018),
        (0.18, 0.2, 0.22),
    )

    wheel_defs = (
        ("left_front_wheel", wheel_base / 2, track_width / 2),
        ("left_rear_wheel", -wheel_base / 2, track_width / 2),
        ("right_front_wheel", wheel_base / 2, -track_width / 2),
        ("right_rear_wheel", -wheel_base / 2, -track_width / 2),
    )
    for name, x, y in wheel_defs:
        wheel_path = _wheel(stage, prim_path, name, (x, y, wheel_radius), wheel_radius)
        stage.DefinePrim(f"{prim_path}/{name}_joint", "Xform")

    return prim_path
