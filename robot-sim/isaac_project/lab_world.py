"""LabKeeper 실감형 대학 생명공학 연구실 3D 디지털 트윈 월드 매니저 (NVIDIA Isaac Sim).

고정 환경 에셋:
- isaac_project/assets/labkeeper_lab_v2.usda (방안 2 기반 PBR 연구실 장면)
- isaac_project/scene/qr_anchors.json (9개 구역 체크포인트 및 순찰 트랙 좌표)
- isaac_project/scene/object_bindings.json (가상 연구실 물품 ↔ Supabase DB 바인딩)
"""
import json
import math
import os
from isaacsim.storage.native import get_assets_root_path
from pxr import Gf, Sdf, UsdGeom, UsdPhysics

_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS_DIR = os.path.join(_DIR, "assets")
_SCENE_DIR = os.path.join(_DIR, "scene")

LAB_USD_PATH = os.path.join(_ASSETS_DIR, "labkeeper_lab_v2.usda")
QR_ANCHORS_PATH = os.path.join(_SCENE_DIR, "qr_anchors.json")
OBJECT_BINDINGS_PATH = os.path.join(_SCENE_DIR, "object_bindings.json")
GUIDE_TARGETS_PATH = os.path.join(_SCENE_DIR, "guide_targets.json")

# 1. 씬 설정 및 체크포인트 로드
with open(QR_ANCHORS_PATH, "r", encoding="utf-8") as f:
    _qr_data = json.load(f)

LAB_ZONES = _qr_data["zones"]
LAB_TRACK_POINTS_M = [tuple(p) for p in _qr_data["track_points"]]

if os.path.exists(OBJECT_BINDINGS_PATH):
    with open(OBJECT_BINDINGS_PATH, "r", encoding="utf-8") as f:
        OBJECT_BINDINGS = json.load(f).get("bindings", [])
else:
    OBJECT_BINDINGS = []

with open(GUIDE_TARGETS_PATH, "r", encoding="utf-8") as f:
    GUIDE_TARGETS = json.load(f)


def resolve_guide_target(item_name="", scene_object_id="", mode="pickup", location="", category=""):
    """DB 물품명/scene_object_id를 실제 로봇 정차 경로로 변환한다."""
    if mode == "return":
        return dict(GUIDE_TARGETS["rental_room"]["return_station"])
    normalized_name = (item_name or "").casefold()
    for target in GUIDE_TARGETS["targets"]:
        if scene_object_id and target["scene_object_id"] == scene_object_id:
            return dict(target)
        query = target["item_query"].casefold()
        if normalized_name and (query in normalized_name or normalized_name in query):
            return dict(target)
    category_target = GUIDE_TARGETS.get("category_defaults", {}).get((category or "").upper())
    if category_target:
        return dict(category_target)
    location_target = GUIDE_TARGETS.get("location_defaults", {}).get(location or "")
    if location_target:
        return dict(location_target)
    return None


def get_all_checkpoints():
    """9개 구역 체크포인트 좌표 및 이름 목록을 반환한다."""
    checkpoints = []
    for z in LAB_ZONES:
        cp = dict(z["checkpoint"])
        cp["name"] = z["name"]
        checkpoints.append(cp)
    return checkpoints


def _add_simready_detail(stage, path, asset_url, position, scale=1.0, rotate_z=0.0):
    """공식 NVIDIA 자산을 인스턴스로 올려 메모리 사용과 로드 비용을 제한한다."""
    prim = stage.DefinePrim(path, "Xform")
    prim.GetReferences().AddReference(asset_url)
    prim.SetInstanceable(True)
    xform = UsdGeom.Xformable(prim)
    xform.AddTranslateOp().Set(Gf.Vec3d(*position))
    if rotate_z:
        xform.AddRotateZOp().Set(rotate_z)
    xform.AddScaleOp().Set(Gf.Vec3f(scale, scale, scale))


def build_lab_environment(stage, items=None):
    """편집 가능한 USD 연구실을 로드하고 물리·DB 바인딩·순찰 요소를 결합한다."""
    print(f"[LabWorld] Loading 3D Biotech Lab USD: {LAB_USD_PATH}")

    # 1. 고정 연구실 USD는 defaultPrim이 없는 /World 기반 파일이라 reference가 아니라
    # sublayer로 합성한다. reference로 붙이면 내용이 조용히 누락되어 빈 장면이 된다.
    asset_layer = Sdf.Layer.FindOrOpen(LAB_USD_PATH)
    if not asset_layer:
        raise RuntimeError(f"실험실 USD를 열 수 없습니다: {LAB_USD_PATH}")
    root_layer = stage.GetRootLayer()
    if asset_layer.identifier not in root_layer.subLayerPaths:
        root_layer.subLayerPaths.append(asset_layer.identifier)

    # 공식 Hospital SimReady 소품을 고밀도 장식으로만 사용한다. 네트워크가 없는 실행은
    # 로컬 v2 USD만으로도 계속 동작하며, 같은 병 세트는 instanceable 참조로 공유한다.
    use_simready = os.environ.get("LABKEEPER_SIMREADY_DETAILS", "1").lower() not in ("0", "false", "no")
    assets_root = get_assets_root_path() if use_simready else None
    if assets_root:
        hospital_props = f"{assets_root}/Isaac/Environments/Hospital/Props"
        detail_specs = (
            # 공식 Hospital SimReady 자산을 연구실 공용 가구/소품에만 사용한다.
            ("/World/SimReadyDetails/MedicalCabinet", "SM_MedicalCabinet_01a.usd", (-6.15, -0.78, 0.0), 0.88, 90.0),
            ("/World/SimReadyDetails/SupplyCart", "SM_SupplyCart_01e.usd", (2.55, 8.05, 0.0), 0.76, 90.0),
            ("/World/SimReadyDetails/UtilityCart", "SM_Cart_01a.usd", (-2.55, 8.05, 0.0), 0.72, -90.0),
            ("/World/SimReadyDetails/LabChairA", "SM_Chair_01a.usd", (-5.28, 6.75, 0.0), 0.78, 90.0),
            ("/World/SimReadyDetails/LabChairB", "SM_Chair_01a.usd", (5.28, 5.15, 0.0), 0.78, -90.0),
            ("/World/SimReadyDetails/FirstAid", "SM_FirstAidKit_01a.usd", (-4.45, -1.74, 1.05), 0.72, 0.0),
            ("/World/SimReadyDetails/TrashCan", "SM_TrashCan.usd", (5.45, 8.05, 0.0), 0.78, 0.0),
            ("/World/SimReadyDetails/ReagentBottleSetA", "SM_PillBottleSet_01a.usd", (-0.35, 15.02, 0.94), 0.92, 0.0),
            ("/World/SimReadyDetails/ReagentBottleSetB", "SM_PillBottleSet_01b.usd", (0.25, 15.02, 0.94), 0.92, 0.0),
            ("/World/SimReadyDetails/RentalUtilityCart", "SM_Cart_01a.usd", (-2.65, -4.05, 0.0), 0.64, 90.0),
            ("/World/SimReadyDetails/RentalDeskChair", "SM_Chair_01a.usd", (3.55, -9.18, 0.0), 0.72, 0.0),
            ("/World/SimReadyDetails/RentalTrashCan", "SM_TrashCan.usd", (6.20, -9.25, 0.0), 0.72, 0.0),
        )
        for prim_path, filename, position, scale, rotate_z in detail_specs:
            _add_simready_detail(stage, prim_path, f"{hospital_props}/{filename}", position, scale, rotate_z)

    # 씬 객체에는 재고 사본이나 QR을 넣지 않고 바인딩 키만 메타데이터로 붙인다.
    normalized_items = items or []
    for binding in OBJECT_BINDINGS:
        prim = stage.GetPrimAtPath(binding["prim_path"])
        if not prim.IsValid():
            print(f"[LabWorld] binding prim not found: {binding['prim_path']}")
            continue
        prim.CreateAttribute("labkeeper:sceneObjectId", Sdf.ValueTypeNames.String).Set(binding["scene_object_id"])
        prim.CreateAttribute("labkeeper:itemQuery", Sdf.ValueTypeNames.String).Set(binding["item_query"])
        prim.CreateAttribute("labkeeper:room", Sdf.ValueTypeNames.String).Set(binding["room"])
        prim.CreateAttribute("labkeeper:displayMode", Sdf.ValueTypeNames.String).Set(binding["display_mode"])
        guide_target = resolve_guide_target(scene_object_id=binding["scene_object_id"])
        if guide_target:
            prim.CreateAttribute("labkeeper:shelfCode", Sdf.ValueTypeNames.String).Set(guide_target["shelf_code"])
            prim.CreateAttribute("labkeeper:zoneType", Sdf.ValueTypeNames.String).Set(guide_target["zone_type"])
            prim.CreateAttribute("labkeeper:accessLevel", Sdf.ValueTypeNames.String).Set(guide_target["access_level"])
            prim.CreateAttribute("labkeeper:navTarget", Sdf.ValueTypeNames.Float2).Set(
                Gf.Vec2f(*guide_target["target"])
            )
        query = binding["item_query"].casefold()
        matched = next((item for item in normalized_items if query in item.get("name", "").casefold()), None)
        if matched:
            prim.CreateAttribute("labkeeper:itemId", Sdf.ValueTypeNames.Int64).Set(int(matched["id"]))
        elif normalized_items:
            print(f"[LabWorld] Supabase item not matched: {binding['scene_object_id']} ({binding['item_query']})")

    # 2. 바닥 노란색 자율주행 순찰 라인트랙
    for i in range(len(LAB_TRACK_POINTS_M) - 1):
        p1 = LAB_TRACK_POINTS_M[i]
        p2 = LAB_TRACK_POINTS_M[i + 1]
        mid_x = (p1[0] + p2[0]) / 2.0
        mid_y = (p1[1] + p2[1]) / 2.0
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        angle_deg = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))

        seg = UsdGeom.Cube.Define(stage, f"/World/Track/Seg_{i}")
        seg.CreateSizeAttr(1.0)
        seg.CreateDisplayColorAttr([(0.95, 0.82, 0.05)])
        xf = UsdGeom.Xformable(seg)
        xf.AddTranslateOp().Set(Gf.Vec3d(mid_x, mid_y, 0.003))
        xf.AddRotateZOp().Set(angle_deg)
        xf.AddScaleOp().Set(Gf.Vec3f(length, 0.04, 0.002))

    # 3. 9개 구역 시각적 QR 체크포인트. 큰 컬러 타일 대신 실제 바닥 QR 라벨 형태.
    for idx, zone in enumerate(LAB_ZONES):
        cp = zone["checkpoint"]
        pad = UsdGeom.Cube.Define(stage, f"/World/Checkpoints/Pad_{idx}")
        pad.CreateSizeAttr(1.0)
        pad.CreateDisplayColorAttr([(0.025, 0.030, 0.032)])
        xf = UsdGeom.Xformable(pad)
        xf.AddTranslateOp().Set(Gf.Vec3d(cp["x"], cp["y"], 0.004))
        xf.AddScaleOp().Set(Gf.Vec3f(0.26, 0.26, 0.002))

        inset = UsdGeom.Cube.Define(stage, f"/World/Checkpoints/Inset_{idx}")
        inset.CreateSizeAttr(1.0)
        inset.CreateDisplayColorAttr([(0.88, 0.90, 0.88)])
        inset_xf = UsdGeom.Xformable(inset)
        inset_xf.AddTranslateOp().Set(Gf.Vec3d(cp["x"], cp["y"], 0.006))
        inset_xf.AddScaleOp().Set(Gf.Vec3f(0.205, 0.205, 0.002))
        # 구역 인덱스로 결정되는 고정 패턴이며 실제 QR 비밀값은 포함하지 않는다.
        for cell in range(25):
            row, col = divmod(cell, 5)
            if ((cell * 7 + idx * 11) % 5) < 2 or cell in (0, 4, 20, 24):
                block = UsdGeom.Cube.Define(stage, f"/World/Checkpoints/QR_{idx}_{cell}")
                block.CreateSizeAttr(1.0)
                block.CreateDisplayColorAttr([(0.02, 0.025, 0.026)])
                block_xf = UsdGeom.Xformable(block)
                block_xf.AddTranslateOp().Set(Gf.Vec3d(
                    cp["x"] + (col - 2) * 0.034,
                    cp["y"] + (row - 2) * 0.034,
                    0.008,
                ))
                block_xf.AddScaleOp().Set(Gf.Vec3f(0.027, 0.027, 0.002))

    # 4. 동적 장애물 (초음파 감지용)
    obs = UsdGeom.Cube.Define(stage, "/World/Obstacle")
    obs.CreateSizeAttr(1.0)
    obs.CreateDisplayColorAttr([(0.85, 0.20, 0.20)])
    xf_obs = UsdGeom.Xformable(obs)
    xf_obs.AddTranslateOp().Set(Gf.Vec3d(0.0, -10.0, 0.15))
    xf_obs.AddScaleOp().Set(Gf.Vec3f(0.3, 0.3, 0.3))

    print("[LabWorld] 3D Biotechnology Lab Digital Twin Loaded Successfully!")
