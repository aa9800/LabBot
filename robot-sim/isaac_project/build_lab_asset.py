"""실제 대학 생명공학 연구실에 가까운 LabBot USD 장면 생성기."""
import math
import os

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(ROOT_DIR, "assets", "labkeeper_lab_v2.usda")


def material(
    stage, name, color, roughness=0.45, metallic=0.0, opacity=1.0,
    emissive=None, clearcoat=0.0, clearcoat_roughness=0.1, ior=1.5,
):
    """RTX에서 유리·금속·코팅 차이가 나도록 한 UsdPreviewSurface 재질."""
    mat = UsdShade.Material.Define(stage, f"/World/Looks/{name}")
    shader = UsdShade.Shader.Define(stage, f"/World/Looks/{name}/PreviewSurface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
    shader.CreateInput("ior", Sdf.ValueTypeNames.Float).Set(ior)
    shader.CreateInput("clearcoat", Sdf.ValueTypeNames.Float).Set(clearcoat)
    shader.CreateInput("clearcoatRoughness", Sdf.ValueTypeNames.Float).Set(clearcoat_roughness)
    if opacity < 1.0:
        shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
    if emissive:
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emissive))
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def bind(prim, mat):
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat)


def cube(stage, path, pos, size, mat, collision=False, rotate_z=0.0):
    obj = UsdGeom.Cube.Define(stage, path)
    obj.CreateSizeAttr(1.0)
    xf = UsdGeom.Xformable(obj)
    xf.AddTranslateOp().Set(Gf.Vec3d(*pos))
    if rotate_z:
        xf.AddRotateZOp().Set(rotate_z)
    xf.AddScaleOp().Set(Gf.Vec3f(*size))
    bind(obj.GetPrim(), mat)
    if collision:
        UsdPhysics.CollisionAPI.Apply(obj.GetPrim())
    return obj.GetPrim()


def cylinder(stage, path, pos, radius, height, mat, axis="Z", collision=False):
    obj = UsdGeom.Cylinder.Define(stage, path)
    obj.CreateAxisAttr(axis)
    obj.CreateRadiusAttr(radius)
    obj.CreateHeightAttr(height)
    UsdGeom.Xformable(obj).AddTranslateOp().Set(Gf.Vec3d(*pos))
    bind(obj.GetPrim(), mat)
    if collision:
        UsdPhysics.CollisionAPI.Apply(obj.GetPrim())
    return obj.GetPrim()


def bench(stage, path, x, y, length, depth, mats, along_y=True, sink=False):
    """페놀 상판, 하부 모듈장, 서비스 스파인으로 구성한 실제형 실험대."""
    sx, sy = (depth, length) if along_y else (length, depth)
    cube(stage, f"{path}/Worktop", (x, y, 0.91), (sx, sy, 0.055), mats["worktop"], True)
    cube(stage, f"{path}/ServiceSpine", (x, y, 1.18),
         (0.10 if along_y else sx * 0.90, sy * 0.88 if along_y else 0.10, 0.48), mats["spine"])
    service_count = max(2, int(length / 1.25))
    for port_idx in range(service_count):
        offset = -length * 0.42 + port_idx * (length * 0.84 / max(1, service_count - 1))
        px, py = (x, y + offset) if along_y else (x + offset, y)
        face_x = px + (-0.056 if x > 0 else 0.056) if along_y else px
        face_y = py if along_y else py - 0.056
        cube(stage, f"{path}/PowerPort_{port_idx}", (face_x, face_y, 1.20),
             (0.012, 0.085, 0.075) if along_y else (0.085, 0.012, 0.075), mats["outlet"])
        cylinder(stage, f"{path}/GasPort_{port_idx}", (face_x, face_y, 1.34), 0.026, 0.026,
                 mats["yellow"], axis="X" if along_y else "Y")
    count = max(2, int(length / 0.72))
    for idx in range(count):
        offset = -length * 0.5 + (idx + 0.5) * length / count
        px, py = (x, y + offset) if along_y else (x + offset, y)
        cw, cd = ((sx * 0.72, length / count - 0.055) if along_y
                  else (length / count - 0.055, sy * 0.72))
        cube(stage, f"{path}/Cabinet_{idx}", (px, py, 0.43), (cw, cd, 0.74), mats["cabinet"], True)
        fx = px + (sx * 0.39 if along_y and x < 0 else -sx * 0.39 if along_y else 0)
        fy = py if along_y else py + (sy * 0.39 if y < 7 else -sy * 0.39)
        hs = (0.018, cd * 0.52, 0.018) if along_y else (cw * 0.52, 0.018, 0.018)
        cube(stage, f"{path}/Handle_{idx}", (fx, fy, 0.66), hs, mats["steel"])
    if sink:
        cube(stage, f"{path}/SinkBasin", (x, y, 0.935),
             (sx * 0.52, 0.46 if along_y else sy * 0.52, 0.025), mats["sink"])
        faucet_x, faucet_y = (x, y + 0.32) if along_y else (x + 0.32, y)
        cylinder(stage, f"{path}/FaucetStem", (faucet_x, faucet_y, 1.14), 0.018, 0.42, mats["steel"])
        cylinder(stage, f"{path}/FaucetNeck", (faucet_x, faucet_y - 0.10, 1.34), 0.018, 0.22, mats["steel"], axis="Y")


def wall_cabinets(stage, path, x, y, length, mats):
    count = max(2, int(length / 0.75))
    for idx in range(count):
        py = y - length * 0.5 + (idx + 0.5) * length / count
        sy = length / count - 0.035
        cube(stage, f"{path}/Unit_{idx}", (x, py, 2.18), (0.34, sy, 0.68), mats["upper"])
        face_x = x - 0.18 if x > 0 else x + 0.18
        cube(stage, f"{path}/Door_{idx}", (face_x, py, 2.18), (0.012, sy * 0.91, 0.59), mats["glass"])


def screen(stage, path, pos, mats, width=0.18):
    x, y, z = pos
    cube(stage, f"{path}/Housing", pos, (width, 0.045, width * 0.62), mats["device"])
    cube(stage, f"{path}/Display", (x, y - 0.026, z + 0.004),
         (width * 0.78, 0.007, width * 0.40), mats["screen"])


def bottle(stage, path, pos, mats, clear=False, radius=0.032, height=0.145):
    cylinder(stage, f"{path}/Body", pos, radius, height, mats["clear"] if clear else mats["amber"])
    cylinder(stage, f"{path}/Cap", (pos[0], pos[1], pos[2] + height * 0.56),
             radius * 0.66, height * 0.16, mats["cap"])
    cube(stage, f"{path}/Label", (pos[0], pos[1] - radius * 1.02, pos[2]),
         (radius * 1.48, 0.004, height * 0.34), mats["label"])


def beaker(stage, path, pos, mats, radius=0.09, height=0.18):
    """투명 용기, 두꺼운 림, 내용물로 구성한 비커."""
    UsdGeom.Xform.Define(stage, path)
    cylinder(stage, f"{path}/Glass", pos, radius, height, mats["clear"])
    cylinder(stage, f"{path}/Liquid", (pos[0], pos[1], pos[2] - height * 0.13),
             radius * 0.88, height * 0.55, mats["teal"])
    cylinder(stage, f"{path}/Rim", (pos[0], pos[1], pos[2] + height * 0.51),
             radius * 1.05, 0.012, mats["steel"])


def flask(stage, path, pos, mats, radius=0.105):
    """둥근 몸체와 좁은 목을 갖는 실험용 플라스크."""
    UsdGeom.Xform.Define(stage, path)
    body = UsdGeom.Sphere.Define(stage, f"{path}/Body")
    UsdGeom.Xformable(body).AddTranslateOp().Set(Gf.Vec3d(pos[0], pos[1], pos[2]))
    UsdGeom.Xformable(body).AddScaleOp().Set(Gf.Vec3f(radius, radius, radius * 1.12))
    bind(body.GetPrim(), mats["clear"])
    cylinder(stage, f"{path}/Neck", (pos[0], pos[1], pos[2] + radius * 1.55),
             radius * 0.34, radius * 1.12, mats["clear"])
    cylinder(stage, f"{path}/Liquid", (pos[0], pos[1], pos[2] - radius * 0.20),
             radius * 0.73, radius * 0.75, mats["blue"])


def tube_rack(stage, path, x, y, mats, color="teal"):
    cube(stage, f"{path}/Rack", (x, y, 1.01), (0.36, 0.20, 0.09), mats[color])
    for row in range(2):
        for col in range(6):
            tx, ty = x - 0.145 + col * 0.058, y - 0.045 + row * 0.09
            cylinder(stage, f"{path}/Tube_{row}_{col}", (tx, ty, 1.12), 0.013, 0.20, mats["clear"])
            cylinder(stage, f"{path}/Cap_{row}_{col}", (tx, ty, 1.225), 0.015, 0.025,
                     mats["blue"] if col % 2 else mats["red"])


def monitor(stage, path, x, y, mats):
    cube(stage, f"{path}/Panel", (x, y, 1.36), (0.52, 0.09, 0.34), mats["device"])
    cube(stage, f"{path}/Display", (x, y - 0.052, 1.36), (0.45, 0.012, 0.27), mats["screen"])
    cylinder(stage, f"{path}/Stand", (x, y, 1.08), 0.025, 0.32, mats["steel"])
    cube(stage, f"{path}/Base", (x, y, 0.96), (0.30, 0.20, 0.035), mats["device"])


def pipette(stage, path, pos, mats, accent="teal"):
    """플런저·손가락 걸이·콘·팁을 분리한 마이크로피펫."""
    x, y, z = pos
    UsdGeom.Xform.Define(stage, path)
    cylinder(stage, f"{path}/Grip", (x, y, z), 0.024, 0.22, mats["device_white"])
    cylinder(stage, f"{path}/VolumeRing", (x, y, z + 0.075), 0.028, 0.035, mats[accent])
    cylinder(stage, f"{path}/Plunger", (x, y, z + 0.145), 0.017, 0.075, mats["black"])
    cylinder(stage, f"{path}/Shaft", (x, y, z - 0.17), 0.010, 0.18, mats["steel"])
    cylinder(stage, f"{path}/DisposableTip", (x, y, z - 0.295), 0.007, 0.10, mats["clear"])
    cube(stage, f"{path}/FingerHook", (x + 0.030, y, z + 0.03), (0.048, 0.030, 0.020), mats[accent])


def pipette_kit(stage, path, pos, mats):
    """이동용 피펫 케이스. DB 바인딩은 상위 Xform 경로에 유지된다."""
    x, y, z = pos
    UsdGeom.Xform.Define(stage, path)
    cube(stage, f"{path}/CaseLower", (x, y, z), (0.60, 0.37, 0.18), mats["device_white"])
    cube(stage, f"{path}/CaseLid", (x, y + 0.13, z + 0.13), (0.58, 0.10, 0.18), mats["clear"], rotate_z=0.0)
    for index, px in enumerate((x - 0.19, x - 0.065, x + 0.065, x + 0.19)):
        pipette(stage, f"{path}/Pipette_{index}", (px, y - 0.01, z + 0.31), mats,
                accent="teal" if index % 2 == 0 else "blue")
    cube(stage, f"{path}/Latch", (x, y - 0.195, z + 0.02), (0.12, 0.018, 0.055), mats["steel"])


def tip_box(stage, path, pos, mats, accent="blue"):
    """투명 뚜껑 안에 팁 배열이 보이는 마이크로피펫 팁 박스."""
    x, y, z = pos
    UsdGeom.Xform.Define(stage, path)
    cube(stage, f"{path}/Base", (x, y, z), (0.34, 0.32, 0.13), mats[accent])
    cube(stage, f"{path}/ClearLid", (x, y, z + 0.09), (0.35, 0.33, 0.055), mats["clear"])
    for row in range(3):
        for col in range(4):
            cylinder(stage, f"{path}/Tip_{row}_{col}",
                     (x - 0.105 + col * 0.07, y - 0.075 + row * 0.075, z + 0.105),
                     0.008, 0.08, mats["device_white"])
    cube(stage, f"{path}/FrontLabel", (x, y - 0.166, z), (0.21, 0.010, 0.07), mats["label"])


def microcentrifuge(stage, path, pos, mats):
    """로터·투명 뚜껑·히지·조작창을 갖춘 보상형 마이크로 원심분리기."""
    x, y, z = pos
    UsdGeom.Xform.Define(stage, path)
    cylinder(stage, f"{path}/Housing", (x, y, z), 0.27, 0.30, mats["device_white"])
    cylinder(stage, f"{path}/RotorWell", (x, y, z + 0.16), 0.205, 0.035, mats["black"])
    cylinder(stage, f"{path}/Rotor", (x, y, z + 0.185), 0.145, 0.038, mats["steel"])
    for index in range(8):
        angle = math.radians(index * 45)
        cylinder(stage, f"{path}/TubeSlot_{index}",
                 (x + math.cos(angle) * 0.095, y + math.sin(angle) * 0.095, z + 0.22),
                 0.018, 0.055, mats["teal"] if index % 2 == 0 else mats["blue"])
    cylinder(stage, f"{path}/ClearLid", (x, y, z + 0.255), 0.235, 0.055, mats["clear"])
    cube(stage, f"{path}/Hinge", (x, y + 0.25, z + 0.22), (0.18, 0.055, 0.07), mats["frame"])
    screen(stage, f"{path}/Control", (x, y - 0.275, z + 0.02), mats, 0.14)


def digital_scale(stage, path, pos, mats):
    """스테인리스 계량판·수평조절발·전면 표시창을 갖춘 전자저울."""
    x, y, z = pos
    UsdGeom.Xform.Define(stage, path)
    cube(stage, f"{path}/Housing", (x, y, z), (0.54, 0.40, 0.11), mats["device"])
    cylinder(stage, f"{path}/Pan", (x, y + 0.015, z + 0.085), 0.18, 0.025, mats["steel"])
    for index, (dx, dy) in enumerate(((-0.21, -0.14), (0.21, -0.14), (-0.21, 0.14), (0.21, 0.14))):
        cylinder(stage, f"{path}/Foot_{index}", (x + dx, y + dy, z - 0.075), 0.025, 0.035, mats["black"])
    screen(stage, f"{path}/Control", (x, y - 0.215, z + 0.01), mats, 0.17)
    for index, dx in enumerate((-0.13, 0.13)):
        cylinder(stage, f"{path}/Button_{index}", (x + dx, y - 0.226, z + 0.01), 0.023, 0.012,
                 mats["green"] if index == 0 else mats["red"], axis="Y")


def microscope(stage, path, pos, mats):
    """베이스·조명·스테이지·터렛·이중 접안부를 갖춘 광학 현미경."""
    x, y, z = pos
    UsdGeom.Xform.Define(stage, path)
    cube(stage, f"{path}/Base", (x, y, z), (0.38, 0.44, 0.08), mats["device"])
    cylinder(stage, f"{path}/Illuminator", (x, y - 0.04, z + 0.065), 0.075, 0.035, mats["screen"])
    cube(stage, f"{path}/Arm", (x, y + 0.14, z + 0.30), (0.12, 0.12, 0.55), mats["device_white"], rotate_z=-8.0)
    cube(stage, f"{path}/Stage", (x, y - 0.025, z + 0.25), (0.30, 0.27, 0.030), mats["steel"])
    cube(stage, f"{path}/Slide", (x, y - 0.07, z + 0.275), (0.12, 0.05, 0.008), mats["clear"])
    cylinder(stage, f"{path}/Turret", (x, y - 0.025, z + 0.43), 0.085, 0.05, mats["frame"])
    for index, dx in enumerate((-0.045, 0.0, 0.045)):
        cylinder(stage, f"{path}/Objective_{index}", (x + dx, y - 0.03, z + 0.36),
                 0.014, 0.11 - index * 0.012, mats["black"])
    cube(stage, f"{path}/Head", (x, y + 0.02, z + 0.58), (0.20, 0.24, 0.16), mats["device_white"])
    for index, dx in enumerate((-0.055, 0.055)):
        cylinder(stage, f"{path}/Eyepiece_{index}", (x + dx, y - 0.105, z + 0.70),
                 0.028, 0.20, mats["black"], axis="Y")
    for index, dx in enumerate((-0.19, 0.19)):
        cylinder(stage, f"{path}/FocusKnob_{index}", (x + dx, y + 0.12, z + 0.34),
                 0.052, 0.045, mats["black"], axis="X")


def stool(stage, path, x, y, mats):
    cylinder(stage, f"{path}/Seat", (x, y, 0.58), 0.21, 0.10, mats["seat"])
    cylinder(stage, f"{path}/Post", (x, y, 0.31), 0.035, 0.50, mats["steel"])
    for idx, (dx, dy) in enumerate(((0.18, 0), (-0.18, 0), (0, 0.18), (0, -0.18))):
        cube(stage, f"{path}/Foot_{idx}", (x + dx * 0.5, y + dy * 0.5, 0.08),
             (abs(dx) + 0.04 if dx else 0.035, abs(dy) + 0.04 if dy else 0.035, 0.035), mats["steel"])


def tall_cabinet(stage, path, x, y, w, d, h, mats, color="cabinet"):
    cube(stage, f"{path}/Body", (x, y, h / 2), (w, d, h), mats[color], True)
    fy = y - d * 0.505
    cube(stage, f"{path}/DoorLeft", (x - w * 0.255, fy, h * 0.51), (w * 0.47, 0.018, h * 0.91), mats["upper"])
    cube(stage, f"{path}/DoorRight", (x + w * 0.255, fy, h * 0.51), (w * 0.47, 0.018, h * 0.91), mats["upper"])
    cube(stage, f"{path}/HandleL", (x - 0.055, fy - 0.012, h * 0.55), (0.012, 0.018, 0.22), mats["steel"])
    cube(stage, f"{path}/HandleR", (x + 0.055, fy - 0.012, h * 0.55), (0.012, 0.018, 0.22), mats["steel"])


def rental_shelf(stage, path, x, y, mats, facing="east"):
    """대여실용 개방 선반. 각 칸은 DB의 shelf_code와 1:1로 대응한다."""
    for dx in (-0.72, 0.72):
        for dy_idx, dy in enumerate((-0.24, 0.24)):
            cube(stage, f"{path}/Post_{'L' if dx < 0 else 'R'}_{dy_idx}", (x + dx, y + dy, 1.05),
                 (0.05, 0.05, 2.10), mats["frame"], True)
    for shelf_idx in range(4):
        z = 0.18 + shelf_idx * 0.55
        cube(stage, f"{path}/Shelf_{shelf_idx}", (x, y, z), (1.52, 0.58, 0.05), mats["steel"], True)
        for col in range(3):
            bx = x - 0.49 + col * 0.49
            cube(stage, f"{path}/Bin_{shelf_idx}_{col}", (bx, y, z + 0.17),
                 (0.40, 0.42, 0.27), mats["teal"] if (shelf_idx + col) % 2 == 0 else mats["blue"])
            cube(stage, f"{path}/BinLabel_{shelf_idx}_{col}", (bx, y - 0.218, z + 0.17),
                 (0.24, 0.012, 0.085), mats["label"])
        cube(stage, f"{path}/RowMarker_{shelf_idx}", (x - 0.78, y - 0.25, z + 0.08),
             (0.08, 0.025, 0.14), mats["yellow"])
    label_y = y - 0.315 if facing == "south" else y
    cube(stage, f"{path}/Header", (x, label_y, 2.28), (1.54, 0.10, 0.28), mats["sign"])
    cube(stage, f"{path}/HeaderAccent", (x - 0.62, label_y - 0.058, 2.28), (0.16, 0.018, 0.20), mats["green"])


def wall_storage_bay(stage, path, x, y, mats, inward="east", accent="teal"):
    """벽을 따라 세우는 고밀도 비품 선반. 중앙 통로 방향으로 라벨과 바구니가 보인다."""
    face_x = x + 0.34 if inward == "east" else x - 0.34
    for side_idx, dy in enumerate((-0.82, 0.82)):
        cube(stage, f"{path}/Post_{side_idx}", (x, y + dy, 1.12), (0.055, 0.055, 2.24), mats["frame"], True)
    for shelf_idx in range(5):
        z = 0.16 + shelf_idx * 0.47
        cube(stage, f"{path}/Shelf_{shelf_idx}", (x, y, z), (0.58, 1.76, 0.045), mats["steel"], True)
        if shelf_idx < 4:
            for col in range(4):
                by = y - 0.60 + col * 0.40
                bin_mat = mats[accent] if (shelf_idx + col) % 2 == 0 else mats["upper"]
                cube(stage, f"{path}/Bin_{shelf_idx}_{col}", (face_x, by, z + 0.15),
                     (0.34, 0.31, 0.24), bin_mat)
                cube(stage, f"{path}/BinLabel_{shelf_idx}_{col}",
                     (face_x + (0.18 if inward == "east" else -0.18), by, z + 0.16),
                     (0.012, 0.18, 0.075), mats["label"])
    cube(stage, f"{path}/Header", (face_x, y, 2.40), (0.045, 1.76, 0.28), mats["sign"])
    cube(stage, f"{path}/HeaderAccent", (face_x + (0.028 if inward == "east" else -0.028), y - 0.68, 2.40),
         (0.014, 0.26, 0.20), mats[accent])


def open_glass_room_front(stage, path, x, y_min, y_max, door_start, mats, accent="blue"):
    """중앙 복도 쪽 전문실 전면. 1.2m 유효폭 자동문을 열린 상태로 표현한다."""
    door_width = 1.20
    door_end = min(door_start + door_width, y_max - 0.18)
    sections = ((y_min, door_start), (door_end, y_max))
    section_idx = 0
    for start, end in sections:
        length = end - start
        if length < 0.16:
            continue
        center = (start + end) * 0.5
        cube(stage, f"{path}/Glass_{section_idx}", (x, center, 1.52),
             (0.040, length, 2.66), mats["glass"], True)
        cube(stage, f"{path}/KickPlate_{section_idx}", (x, center, 0.10),
             (0.065, length, 0.20), mats["steel"], True)
        for edge_idx, edge_y in enumerate((start, end)):
            cube(stage, f"{path}/Frame_{section_idx}_{edge_idx}", (x, edge_y, 1.52),
                 (0.075, 0.055, 2.72), mats["frame"])
        section_idx += 1
    # 상부 레일과 열린 문짝(고정 유리 뒤로 포개진 위치), 문턱·상태등.
    door_center = (door_start + door_end) * 0.5
    parked_center = min(y_max - 0.30, door_end + door_width * 0.46)
    cube(stage, f"{path}/DoorRail", (x, door_center, 2.76), (0.10, door_width + 0.22, 0.11), mats["frame"])
    cube(stage, f"{path}/ParkedDoor", (x + (0.018 if x < 0 else -0.018), parked_center, 1.48),
         (0.032, min(door_width * 0.92, y_max - door_end), 2.52), mats["glass"])
    cube(stage, f"{path}/Threshold", (x, door_center, 0.022), (0.72, door_width, 0.025), mats["steel"])
    reader_x = x + (0.12 if x < 0 else -0.12)
    cube(stage, f"{path}/DoorButton", (reader_x, door_start - 0.10, 1.08), (0.10, 0.10, 0.20), mats["device"])
    cube(stage, f"{path}/DoorButtonLight", (reader_x + (0.055 if x < 0 else -0.055), door_start - 0.10, 1.10),
         (0.012, 0.055, 0.075), mats[accent])
    cube(stage, f"{path}/RoomID", (x, door_center, 2.58), (0.09, 0.82, 0.22), mats["sign"])


def floor_arrow(stage, path, x, y, mats, color="green", rotate_z=0.0):
    """대여실 보행/로봇 동선을 읽기 쉽게 만드는 얇은 바닥 화살표."""
    cube(stage, f"{path}/Shaft", (x, y, 0.025), (0.16, 0.62, 0.012), mats[color], rotate_z=rotate_z)
    cube(stage, f"{path}/HeadL", (x - 0.13, y + 0.27, 0.026), (0.12, 0.34, 0.012), mats[color], rotate_z=-38 + rotate_z)
    cube(stage, f"{path}/HeadR", (x + 0.13, y + 0.27, 0.026), (0.12, 0.34, 0.012), mats[color], rotate_z=38 + rotate_z)


def zone_sign(stage, path, pos, accent, mats):
    cube(stage, f"{path}/Backplate", pos, (1.05, 0.035, 0.25), mats["sign"])
    cube(stage, f"{path}/Accent", (pos[0] - 0.49, pos[1] - 0.022, pos[2]), (0.045, 0.012, 0.21), accent)
    stage.GetPrimAtPath(f"{path}/Backplate").CreateAttribute(
        "labkeeper:zoneName", Sdf.ValueTypeNames.String).Set(path.rsplit("/", 1)[-1])


def build():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    stage = Usd.Stage.CreateNew(OUTPUT_PATH)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Xform.Define(stage, "/World/Looks")
    mats = {
        "floor": material(stage, "SpeckledEpoxy", (0.26, 0.31, 0.33), 0.34, clearcoat=0.18, clearcoat_roughness=0.32),
        "aisle": material(stage, "AisleEpoxy", (0.39, 0.45, 0.47), 0.29, clearcoat=0.22, clearcoat_roughness=0.28),
        "wall": material(stage, "WarmLabWall", (0.72, 0.75, 0.73), 0.68),
        "ceiling": material(stage, "AcousticCeiling", (0.78, 0.80, 0.78), 0.82),
        "glass": material(stage, "SafetyGlass", (0.30, 0.55, 0.58), 0.055, opacity=0.20, clearcoat=0.72, clearcoat_roughness=0.035, ior=1.52),
        "frame": material(stage, "DarkFrame", (0.045, 0.065, 0.072), 0.30, 0.72),
        "worktop": material(stage, "BlackPhenolic", (0.035, 0.045, 0.050), 0.24, clearcoat=0.32, clearcoat_roughness=0.17),
        "spine": material(stage, "ServiceSpine", (0.20, 0.24, 0.25), 0.42),
        "steel": material(stage, "BrushedSteel", (0.42, 0.47, 0.48), 0.20, 0.88),
        "sink": material(stage, "SinkSteel", (0.26, 0.31, 0.32), 0.15, 0.92),
        "cabinet": material(stage, "LowerCabinet", (0.42, 0.47, 0.46), 0.48),
        "upper": material(stage, "UpperCabinet", (0.68, 0.72, 0.70), 0.42),
        "device": material(stage, "InstrumentHousing", (0.12, 0.145, 0.155), 0.30, clearcoat=0.16, clearcoat_roughness=0.22),
        "device_white": material(stage, "InstrumentIvory", (0.70, 0.72, 0.69), 0.30, clearcoat=0.20, clearcoat_roughness=0.20),
        "screen": material(stage, "InstrumentDisplay", (0.01, 0.12, 0.14), 0.075, emissive=(0.0, 0.55, 0.68), clearcoat=0.55, clearcoat_roughness=0.04),
        "sign": material(stage, "SignBackplate", (0.10, 0.13, 0.14), 0.36),
        "outlet": material(stage, "OutletPanel", (0.72, 0.75, 0.72), 0.52),
        "teal": material(stage, "LabTeal", (0.02, 0.34, 0.38), 0.38),
        "blue": material(stage, "MedicalBlue", (0.08, 0.24, 0.46), 0.38),
        "green": material(stage, "CultureGreen", (0.08, 0.34, 0.20), 0.42),
        "yellow": material(stage, "SafetyYellow", (0.74, 0.49, 0.035), 0.40),
        "red": material(stage, "SafetyRed", (0.58, 0.025, 0.02), 0.36),
        "purple": material(stage, "FreezerPurple", (0.24, 0.11, 0.38), 0.42),
        "amber": material(stage, "AmberGlass", (0.25, 0.07, 0.012), 0.10, opacity=0.82, clearcoat=0.45, clearcoat_roughness=0.06, ior=1.50),
        "clear": material(stage, "ClearPlastic", (0.54, 0.72, 0.73), 0.075, opacity=0.36, clearcoat=0.58, clearcoat_roughness=0.04, ior=1.48),
        "cap": material(stage, "BottleCap", (0.035, 0.045, 0.05), 0.65),
        "label": material(stage, "BottleLabel", (0.78, 0.74, 0.55), 0.72),
        "black": material(stage, "RubberBlack", (0.012, 0.014, 0.016), 0.78),
        "seat": material(stage, "StoolSeat", (0.07, 0.18, 0.20), 0.60),
        "biohazard": material(stage, "Biohazard", (0.78, 0.52, 0.02), 0.55),
        "floor_detail": material(stage, "FloorJoint", (0.17, 0.21, 0.22), 0.50),
    }

    # 14x18m 보안 실험구역 + 남쪽 14x8m 대여·반납실 확장.
    cube(stage, "/World/LabFloor", (0, 7, -0.06), (14, 18, 0.12), mats["floor"], True)
    cube(stage, "/World/CleanCorridor", (0, 7, 0.008), (4.75, 17.4, 0.016), mats["aisle"])
    walls = (("WestWall", (-7, 7, 1.6), (0.16, 18, 3.2)),
             ("EastWall", (7, 7, 1.6), (0.16, 18, 3.2)),
             ("SouthWallL", (-4.35, -2, 1.6), (5.3, 0.16, 3.2)),
             ("SouthWallR", (4.35, -2, 1.6), (5.3, 0.16, 3.2)),
             ("NorthWall", (0, 16, 1.6), (14, 0.16, 3.2)))
    for name, pos, size in walls:
        cube(stage, f"/World/Architecture/{name}", pos, size, mats["wall"], True)
    cube(stage, "/World/Architecture/EntryHeader", (0, -2, 2.85), (3.4, 0.18, 0.70), mats["wall"])
    for idx, x in enumerate((-1.72, 1.72)):
        cube(stage, f"/World/Architecture/EntryJamb_{idx}", (x, -2, 1.35), (0.12, 0.20, 2.70), mats["frame"])

    # 대여·반납실: 일반 사용자가 접근하는 공간. y=-2의 기존 출입구는 이제 보안 게이트다.
    cube(stage, "/World/RentalWing/Floor", (0, -6.0, -0.06), (14, 8.0, 0.12), mats["aisle"], True)
    cube(stage, "/World/RentalWing/CenterLane", (0, -6.0, 0.008), (3.2, 7.6, 0.016), mats["floor"])
    # 에폭시 바닥의 패널 이음선을 업무 동선을 해치지 않는 정도로만 표현한다.
    for seam_idx, seam_y in enumerate((-8.0, -6.0, -4.0)):
        cube(stage, f"/World/RentalWing/FloorSeamY_{seam_idx}", (0, seam_y, 0.014),
             (13.55, 0.012, 0.004), mats["floor_detail"])
    for seam_idx, seam_x in enumerate((-4.7, -2.35, 2.35, 4.7)):
        cube(stage, f"/World/RentalWing/FloorSeamX_{seam_idx}", (seam_x, -6.0, 0.014),
             (0.012, 7.55, 0.004), mats["floor_detail"])
    cube(stage, "/World/RentalWing/WestWall", (-7, -6.0, 1.6), (0.16, 8.0, 3.2), mats["wall"], True)
    cube(stage, "/World/RentalWing/EastWall", (7, -6.0, 1.6), (0.16, 8.0, 3.2), mats["wall"], True)
    cube(stage, "/World/RentalWing/SouthWallL", (-4.1, -10.0, 1.6), (5.7, 0.16, 3.2), mats["wall"], True)
    cube(stage, "/World/RentalWing/SouthWallR", (4.1, -10.0, 1.6), (5.7, 0.16, 3.2), mats["wall"], True)
    cube(stage, "/World/RentalWing/EntryHeader", (0, -10.0, 2.85), (2.5, 0.18, 0.70), mats["wall"])
    for idx, x in enumerate((-1.32, 1.32)):
        cube(stage, f"/World/RentalWing/EntryJamb_{idx}", (x, -10.0, 1.35), (0.12, 0.20, 2.70), mats["frame"])

    # 보안 경계: 2.1m 유효폭의 양방향 자동 슬라이딩 도어. 문짝은 벽 쪽에 열린 상태로 둔다.
    cube(stage, "/World/RentalWing/SecurityGlassL", (-1.38, -2.02, 1.35), (0.55, 0.035, 2.55), mats["glass"])
    cube(stage, "/World/RentalWing/SecurityGlassR", (1.38, -2.02, 1.35), (0.55, 0.035, 2.55), mats["glass"])
    cube(stage, "/World/RentalWing/SecurityDoorRail", (0, -2.02, 2.73), (3.30, 0.11, 0.12), mats["frame"])
    cube(stage, "/World/RentalWing/SecurityThreshold", (0, -2.02, 0.022), (2.25, 0.42, 0.025), mats["steel"])
    cube(stage, "/World/RentalWing/AccessReader", (1.84, -2.18, 1.15), (0.18, 0.12, 0.28), mats["device"])
    cube(stage, "/World/RentalWing/AccessReaderScreen", (1.84, -2.25, 1.17), (0.12, 0.02, 0.14), mats["screen"])
    cube(stage, "/World/RentalWing/DoorStatusLight", (1.84, -2.25, 1.38), (0.08, 0.02, 0.08), mats["green"])

    # 중앙 픽업 선반은 로봇 정차 좌표에서 손이 닿는 거리로 이동한다.
    rental_shelf(stage, "/World/RentalWing/WestPickupShelf", -3.55, -5.85, mats)
    rental_shelf(stage, "/World/RentalWing/EastPickupShelf", 3.55, -5.85, mats)
    # 양쪽 벽면에는 실제 비품실처럼 연속 선반 6개를 배치하되 중앙 3.2m 통로는 비운다.
    for bay_idx, bay_y in enumerate((-4.25, -6.15, -8.05)):
        wall_storage_bay(stage, f"/World/RentalWing/WestWallStorage_{bay_idx}", -6.55, bay_y,
                         mats, inward="east", accent="teal" if bay_idx < 2 else "yellow")
        wall_storage_bay(stage, f"/World/RentalWing/EastWallStorage_{bay_idx}", 6.55, bay_y,
                         mats, inward="west", accent="blue" if bay_idx < 2 else "green")

    # DB 대표 물품과 연결되는 픽업용 디스플레이 객체.
    pipette_kit(stage, "/World/RentalWing/WestPickupShelf/PipetteKit", (-3.55, -5.22, 1.43), mats)
    for idx in range(3):
        tip_box(stage, f"/World/RentalWing/WestPickupShelf/TipBox_{idx}",
                (-3.95 + idx * 0.40, -6.47, 1.45), mats, "teal" if idx % 2 == 0 else "blue")
    microcentrifuge(stage, "/World/RentalWing/EastPickupShelf/MicroCentrifuge", (3.55, -5.22, 1.52), mats)
    digital_scale(stage, "/World/RentalWing/EastPickupShelf/DigitalScale", (3.55, -6.48, 1.43), mats)

    # 반납 확인대, 셀프 안내 키오스크, 로봇 충전 도크.
    cube(stage, "/World/RentalWing/ReturnDesk", (4.75, -8.55, 0.58), (2.7, 0.72, 1.16), mats["cabinet"], True)
    cube(stage, "/World/RentalWing/ReturnDeskTop", (4.75, -8.55, 1.18), (2.85, 0.82, 0.07), mats["worktop"], True)
    cube(stage, "/World/RentalWing/ReturnDeskWing", (5.83, -7.92, 0.58), (0.72, 1.38, 1.16), mats["cabinet"], True)
    cube(stage, "/World/RentalWing/ReturnDeskWingTop", (5.83, -7.92, 1.18), (0.82, 1.48, 0.07), mats["worktop"], True)
    screen(stage, "/World/RentalWing/ReturnDeskScreen", (4.75, -8.93, 1.55), mats, 0.30)
    cube(stage, "/World/RentalWing/ReturnTray", (4.08, -8.12, 1.25), (0.72, 0.45, 0.08), mats["green"])
    cube(stage, "/World/RentalWing/LabelPrinter", (5.33, -8.20, 1.34), (0.42, 0.34, 0.28), mats["device_white"])
    cube(stage, "/World/RentalWing/PrinterSlot", (5.33, -8.02, 1.35), (0.25, 0.018, 0.045), mats["black"])
    cube(stage, "/World/RentalWing/QRScannerBase", (4.45, -8.18, 1.28), (0.18, 0.16, 0.08), mats["device"])
    cylinder(stage, "/World/RentalWing/QRScannerStem", (4.45, -8.18, 1.45), 0.025, 0.30, mats["frame"])
    cube(stage, "/World/RentalWing/QRScannerHead", (4.45, -8.18, 1.62), (0.18, 0.12, 0.12), mats["screen"])

    # 서측 포장·검수대와 소모품 디테일.
    cube(stage, "/World/RentalWing/PackingBench", (-4.55, -8.62, 0.53), (2.45, 0.72, 1.06), mats["cabinet"], True)
    cube(stage, "/World/RentalWing/PackingBenchTop", (-4.55, -8.62, 1.09), (2.58, 0.82, 0.07), mats["worktop"], True)
    for idx in range(4):
        cube(stage, f"/World/RentalWing/PackingTote_{idx}", (-5.28 + idx * 0.48, -8.55, 1.25),
             (0.38, 0.42, 0.24), mats["teal"] if idx % 2 == 0 else mats["blue"])
        cube(stage, f"/World/RentalWing/PackingLabel_{idx}", (-5.28 + idx * 0.48, -8.32, 1.26),
             (0.22, 0.012, 0.08), mats["label"])

    cube(stage, "/World/RentalWing/KioskBase", (1.25, -8.82, 0.52), (0.60, 0.45, 1.04), mats["device"], True)
    screen(stage, "/World/RentalWing/KioskScreen", (1.25, -9.08, 1.35), mats, 0.48)
    cube(stage, "/World/RentalWing/KioskHeader", (1.25, -9.35, 2.18), (1.25, 0.08, 0.26), mats["sign"])
    cube(stage, "/World/RentalWing/DockPad", (-1.55, -8.72, 0.015), (1.25, 1.05, 0.03), mats["black"])
    cube(stage, "/World/RentalWing/DockStripe", (-1.55, -8.72, 0.034), (0.92, 0.08, 0.012), mats["green"])
    # 구역 바닥 테두리와 진행 화살표. 얇은 비충돌 프림이라 주행 성능에는 영향이 없다.
    for idx, y in enumerate((-3.25, -4.65, -7.15)):
        floor_arrow(stage, f"/World/RentalWing/WayfindingArrow_{idx}", 0.0, y, mats, "green")
    for x in (-2.05, 2.05):
        cube(stage, f"/World/RentalWing/PickupZoneLine_{'L' if x < 0 else 'R'}", (x, -5.95, 0.022),
             (0.045, 3.55, 0.012), mats["yellow"])
    cube(stage, "/World/RentalWing/QueueLine", (1.25, -7.95, 0.022), (1.45, 0.045, 0.012), mats["green"])
    # 천장판은 상부 편집 시야를 막으므로 생략하고, 실제 패널등 하우징으로 높이감을 만든다.

    # 전문실 유리 파티션: 각 실마다 1.2m 열린 자동문을 두고 불투명 하부벽을 없앴다.
    # 복도에서 내부가 보이고 휠체어·카트·사람이 교차해도 병목이 생기지 않는다.
    room_fronts = ((9.02, 11.44, 9.28, "blue"),
                   (11.56, 13.84, 11.80, "teal"),
                   (13.96, 15.92, 14.18, "green"))
    for side, x in (("West", -2.48), ("East", 2.48)):
        for idx, (y_min, y_max, door_start, accent) in enumerate(room_fronts):
            open_glass_room_front(stage, f"/World/Architecture/{side}RoomFront_{idx}",
                                  x, y_min, y_max, door_start, mats, accent)
    for idx, y in enumerate((11.5, 13.9)):
        cube(stage, f"/World/Architecture/WestDivider_{idx}", (-4.73, y, 1.6), (4.4, 0.12, 3.2), mats["wall"], True)
        cube(stage, f"/World/Architecture/EastDivider_{idx}", (4.73, y, 1.6), (4.4, 0.12, 3.2), mats["wall"], True)

    # 메인 오픈랩. 기존 중앙 통로의 가구를 제거하고 양쪽 실험대로 재배치.
    bench(stage, "/World/MainBench/IslandWest", -3.65, 4.25, 7.4, 1.25, mats, sink=True)
    bench(stage, "/World/MainBench/IslandEast", 3.65, 4.25, 7.4, 1.25, mats, sink=True)
    wall_cabinets(stage, "/World/MainBench/WestUpper", -6.58, 4.15, 8.0, mats)
    wall_cabinets(stage, "/World/MainBench/EastUpper", 6.58, 4.15, 8.0, mats)
    bench(stage, "/World/MainBench/WestWallBench", -6.25, 4.15, 8.0, 0.72, mats)
    bench(stage, "/World/MainBench/EastWallBench", 6.25, 4.15, 8.0, 0.72, mats)
    for idx, (x, y) in enumerate(((-2.82, 1.8), (-2.82, 5.4), (2.82, 2.7), (2.82, 6.4))):
        stool(stage, f"/World/MainBench/Stool_{idx}", x, y, mats)

    microscope(stage, "/World/MainBench/MicroscopeBody", (-3.62, 2.10, 0.98), mats)
    microcentrifuge(stage, "/World/MainBench/Centrifuge", (3.66, 2.35, 1.09), mats)
    digital_scale(stage, "/World/MainBench/Scale", (-3.65, 5.72, 1.02), mats)
    cube(stage, "/World/MainBench/PipetteStand", (3.64, 5.55, 1.02), (0.38, 0.18, 0.08), mats["teal"])
    for idx in range(6):
        pipette(stage, f"/World/MainBench/Pipette_{idx}", (3.49 + idx * 0.06, 5.55, 1.25), mats,
                accent="teal" if idx % 2 == 0 else "blue")
    for idx in range(3):
        beaker(stage, f"/World/MainBench/Beaker_{idx}",
               (-3.88 + idx * 0.24, 4.38, 1.07), mats, radius=0.072 + idx * 0.009)
    for idx in range(2):
        flask(stage, f"/World/MainBench/Flask_{idx}",
              (3.48 + idx * 0.30, 3.50, 1.08), mats, radius=0.085 + idx * 0.012)
    for idx in range(3):
        tip_box(stage, f"/World/MainBench/TipBox_{idx}", (3.30 + idx * 0.36, 6.65, 1.02), mats,
                "teal" if idx % 2 == 0 else "blue")
    tube_rack(stage, "/World/MainBench/TubeRackWest", -3.64, 3.45, mats, "blue")
    tube_rack(stage, "/World/MainBench/TubeRackEast", 3.64, 4.45, mats, "teal")
    monitor(stage, "/World/MainBench/ComputerWest", -6.20, 7.10, mats)
    monitor(stage, "/World/MainBench/ComputerEast", 6.20, 3.80, mats)
    for idx, y in enumerate((1.35, 4.35, 7.35)):
        for col in range(4):
            bottle(stage, f"/World/MainBench/WallReagent_{idx}_{col}",
                   (-6.18, y + col * 0.12, 1.03), mats, clear=(col % 3 == 0), radius=0.025, height=0.13)

    # 서측 기기실.
    bench(stage, "/World/West/InstrumentBench1", -4.65, 10.65, 3.3, 0.72, mats, along_y=False)
    cube(stage, "/World/West/Inst1_PCR", (-5.55, 10.65, 1.12), (0.68, 0.55, 0.38), mats["device_white"], True)
    cube(stage, "/World/West/Inst1_PCR_Lid", (-5.55, 10.70, 1.34), (0.56, 0.44, 0.09), mats["device"])
    screen(stage, "/World/West/Inst1_PCR_UI", (-5.55, 10.36, 1.12), mats)
    cube(stage, "/World/West/ElectrophoresisTank", (-4.55, 10.65, 1.06), (0.68, 0.43, 0.22), mats["clear"])
    cube(stage, "/World/West/GelDoc", (-3.55, 10.68, 1.28), (0.62, 0.56, 0.72), mats["device"], True)
    screen(stage, "/World/West/GelDocScreen", (-3.55, 10.37, 1.33), mats, 0.20)
    bench(stage, "/World/West/InstrumentBench2", -4.65, 12.65, 3.3, 0.72, mats, along_y=False)
    cube(stage, "/World/West/Spectrophotometer", (-5.45, 12.65, 1.10), (0.78, 0.52, 0.35), mats["device_white"], True)
    screen(stage, "/World/West/SpectroScreen", (-5.45, 12.36, 1.13), mats)
    cube(stage, "/World/West/HPLC", (-3.92, 12.68, 1.46), (0.78, 0.58, 1.08), mats["cabinet"], True)
    for idx in range(3):
        cube(stage, f"/World/West/HPLC_Module_{idx}", (-3.92, 12.36, 1.19 + idx * 0.31), (0.66, 0.035, 0.23), mats["upper"])
        cube(stage, f"/World/West/HPLC_Light_{idx}", (-4.16, 12.33, 1.19 + idx * 0.31), (0.05, 0.012, 0.035), mats["screen"])

    # 세포배양실.
    cube(stage, "/World/West/Cell_BSC_Base", (-4.55, 14.85, 0.60), (2.65, 0.78, 1.20), mats["cabinet"], True)
    cube(stage, "/World/West/Cell_BSC_Hood", (-4.55, 14.85, 1.78), (2.65, 0.78, 1.02), mats["upper"], True)
    cube(stage, "/World/West/Cell_BSC_Glass", (-4.55, 14.42, 1.52), (2.30, 0.035, 0.62), mats["glass"])
    cube(stage, "/World/West/Cell_BSC_Light", (-4.55, 14.76, 2.16), (1.85, 0.08, 0.045), mats["screen"])
    tall_cabinet(stage, "/World/West/CO2Incubator", -6.15, 14.88, 0.78, 0.76, 2.18, mats, "device")
    screen(stage, "/World/West/CO2Screen", (-6.15, 14.47, 1.92), mats, 0.20)

    # 동측 소모품 랙과 실제 비율의 냉장·냉동고.
    for rack_idx, rx in enumerate((3.45, 5.25)):
        base = "/World/East/Consumables_Shelf" if rack_idx == 0 else f"/World/East/Consumables_Shelf_{rack_idx}"
        for leg_idx, dx in enumerate((-0.66, 0.66)):
            cube(stage, f"{base}/Post_{leg_idx}A", (rx + dx, 10.82, 1.08), (0.045, 0.045, 2.16), mats["frame"], True)
            cube(stage, f"{base}/Post_{leg_idx}B", (rx + dx, 11.30, 1.08), (0.045, 0.045, 2.16), mats["frame"], True)
        for shelf_idx in range(5):
            z = 0.18 + shelf_idx * 0.46
            cube(stage, f"{base}/Shelf_{shelf_idx}", (rx, 11.06, z), (1.42, 0.56, 0.045), mats["steel"])
            for col in range(4):
                box_mat = mats["teal"] if (shelf_idx + col + rack_idx) % 2 == 0 else mats["blue"]
                cube(stage, f"{base}/Bin_{shelf_idx}_{col}", (rx - 0.51 + col * 0.34, 10.98, z + 0.15), (0.27, 0.36, 0.24), box_mat)
    tall_cabinet(stage, "/World/East/Fridge_4C", 3.65, 12.82, 1.08, 0.82, 2.35, mats)
    screen(stage, "/World/East/FridgeDisplay", (3.65, 12.38, 1.99), mats, 0.20)
    tall_cabinet(stage, "/World/East/Freezer_80C_1", 5.02, 12.82, 1.08, 0.82, 2.35, mats, "device_white")
    screen(stage, "/World/East/FreezerDisplay1", (5.02, 12.38, 1.99), mats, 0.20)
    tall_cabinet(stage, "/World/East/Freezer_80C_2", 6.15, 12.82, 1.08, 0.82, 2.35, mats, "device_white")
    screen(stage, "/World/East/FreezerDisplay2", (6.15, 12.38, 1.99), mats, 0.20)

    # 북측 시약실.
    bench(stage, "/World/North/Reagent_Desk", 0, 15.28, 3.8, 0.78, mats, along_y=False)
    cube(stage, "/World/North/Reagent_Desk/PHMeter", (-1.28, 15.25, 1.10), (0.24, 0.20, 0.34), mats["device"])
    screen(stage, "/World/North/Reagent_Desk/PHScreen", (-1.28, 15.13, 1.15), mats, 0.15)
    for row in range(3):
        for col in range(11):
            h = 0.12 + ((row + col) % 3) * 0.025
            bottle(stage, f"/World/North/Reagent_{row}_{col}",
                   (-1.0 + col * 0.20, 15.10 + row * 0.20, 1.04 + row * 0.04), mats,
                   clear=(col % 4 == 0), radius=0.026 + (col % 2) * 0.005, height=h)

    # 안전 설비.
    tall_cabinet(stage, "/World/Safety/FlammableCabinet", 6.18, 14.93, 0.85, 0.72, 2.05, mats, "yellow")
    tall_cabinet(stage, "/World/Safety/PPECabinet", -6.20, -0.75, 0.88, 0.66, 2.08, mats)
    cylinder(stage, "/World/Safety/FireExtinguisher", (5.95, -1.25, 0.39), 0.15, 0.72, mats["red"], collision=True)
    cube(stage, "/World/Safety/ExtinguisherHandle", (5.95, -1.25, 0.80), (0.25, 0.08, 0.07), mats["black"])
    UsdGeom.Xform.Define(stage, "/World/Safety/SpillKit")
    cube(stage, "/World/Safety/SpillKit/Case", (5.25, -1.42, 0.43),
         (0.56, 0.26, 0.64), mats["yellow"], True)
    cube(stage, "/World/Safety/SpillKit/Label", (5.25, -1.575, 0.45),
         (0.40, 0.018, 0.25), mats["green"])
    cube(stage, "/World/Safety/SpillKit/Handle", (5.25, -1.42, 0.79),
         (0.24, 0.055, 0.06), mats["black"])
    cylinder(stage, "/World/Safety/ShowerPipe", (-5.05, -1.48, 1.55), 0.035, 2.65, mats["steel"])
    cylinder(stage, "/World/Safety/ShowerHead", (-5.05, -1.48, 2.72), 0.21, 0.09, mats["yellow"])
    cube(stage, "/World/Safety/EyeWash", (-4.40, -1.47, 0.88), (0.58, 0.36, 0.18), mats["green"], True)
    for idx, x in enumerate((4.55, 5.05)):
        cylinder(stage, f"/World/Safety/WasteBin_{idx}", (x, -1.18, 0.38), 0.22, 0.72,
                 mats["biohazard"] if idx == 0 else mats["device"], collision=True)

    # 과노출을 줄인 천장 패널등.
    for row, y in enumerate((-8.2, -5.2, -2.4, -0.2, 3.3, 6.8, 10.3, 13.8)):
        for col, x in enumerate((-4.7, 0, 4.7)):
            light = UsdLux.RectLight.Define(stage, f"/World/Lights/Panel_{row}_{col}")
            light.CreateIntensityAttr(1120.0)
            light.CreateColorAttr(Gf.Vec3f(0.82, 0.90, 0.98))
            light.CreateWidthAttr(1.20)
            light.CreateHeightAttr(0.42)
            xf = UsdGeom.Xformable(light)
            xf.AddTranslateOp().Set(Gf.Vec3d(x, y, 3.14))
            xf.AddRotateXOp().Set(180.0)
            cube(stage, f"/World/Lights/PanelHousing_{row}_{col}", (x, y, 3.17), (1.28, 0.50, 0.035), mats["upper"])

    # 선반 하부 작업등: 물품 유리·라벨·기기 조작부에 깊이감있는 하이라이트를 만든다.
    task_lights = (
        ("RentalWest", -3.55, -5.82, 2.16, 760.0),
        ("RentalEast", 3.55, -5.82, 2.16, 760.0),
        ("MainWest", -6.16, 4.15, 1.88, 520.0),
        ("MainEast", 6.16, 4.15, 1.88, 520.0),
        ("Reagent", 0.0, 15.03, 2.05, 620.0),
    )
    for name, x, y, z, intensity in task_lights:
        light = UsdLux.RectLight.Define(stage, f"/World/Lights/Task_{name}")
        light.CreateIntensityAttr(intensity)
        light.CreateColorAttr(Gf.Vec3f(0.90, 0.94, 1.0))
        light.CreateWidthAttr(1.10 if "Rental" in name else 1.65)
        light.CreateHeightAttr(0.10)
        xf = UsdGeom.Xformable(light)
        xf.AddTranslateOp().Set(Gf.Vec3d(x, y, z))
        xf.AddRotateXOp().Set(180.0)

    signs = (("RentalReturn", (0, -9.88, 2.45), mats["green"]),
             ("SecureLab", (0, -2.12, 2.45), mats["red"]),
             ("PickupShelfA", (-3.55, -5.49, 2.28), mats["teal"]),
             ("PickupShelfB", (3.55, -5.49, 2.28), mats["blue"]),
             ("ReturnStation", (4.75, -8.16, 2.10), mats["green"]),
             ("RobotDock", (-1.55, -9.25, 0.24), mats["green"]),
             ("GeneralLab", (0, -1.88, 2.45), mats["blue"]),
             ("InstrumentRoom1", (-3.65, 9.76, 2.48), mats["blue"]),
             ("InstrumentRoom2", (-5.15, 11.62, 2.48), mats["teal"]),
             ("CellCulture", (-5.15, 14.02, 2.48), mats["green"]),
             ("ReagentStorage", (0, 14.03, 2.48), mats["yellow"]),
             ("FreezerStorage", (5.05, 14.02, 2.48), mats["purple"]),
             ("ColdStorage", (3.65, 11.62, 2.48), mats["blue"]),
             ("Consumables", (4.45, 9.76, 2.48), mats["yellow"]),
             ("SafetyStation", (4.85, -1.88, 2.48), mats["red"]))
    for name, pos, accent in signs:
        zone_sign(stage, f"/World/ZoneSigns/{name}", pos, accent, mats)

    stage.GetRootLayer().Save()
    print(f"LABKEEPER_LAB_ASSET_BUILT {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
