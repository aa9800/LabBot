"""LabKeeper 실감형 스마트 실험실 3D 디지털 트윈 월드 빌더 (NVIDIA Isaac Sim).

NVIDIA Isaac Sim의 고품질 PBR 재질과 실제 3D 바이오·화학 연구실 기구
(원심분리기, 약품보관장, 생물유해폐기물함, 소화기, 보호안경, 실험대, 트롤리 등)를
프로그래밍 방식으로 배치하여 현실과 완벽히 동기화된 가상 연구실을 구축한다.
"""
import math
from pxr import Gf, UsdGeom, UsdLux

# NVIDIA Nucleus 공용 고품질 3D 에셋 베이스 경로
NUCLEUS_ASSETS_ROOT = "http://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/4.5"

# ── 9개 보관 구역 정의 및 실사 3D 에셋 매핑 ───
LAB_ZONES = [
    {
        "name": "기기실-1",
        "category": "EQUIPMENT",
        "color": (0.15, 0.35, 0.85),  # 세련된 코발트 블루
        "pos": (-2.0, -1.8, 0.0),
        "rot_z": 0.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Office/Desk.usd",
        "secondary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Solder_Station/solder_station.usd",
        "secondary_offset": (-2.0, -1.8, 0.75),
        "checkpoint": {"name": "기기실-1", "x": -2.0, "y": -1.2, "radius": 0.35},
        "sample_items": ["형광현미경", "일반 PCR 장비", "Real-time PCR 장비", "UV-Vis 분광광도계"],
    },
    {
        "name": "기기실-2",
        "category": "EQUIPMENT",
        "color": (0.1, 0.6, 0.8),   # 시안 블루
        "pos": (0.0, -1.8, 0.0),
        "rot_z": 0.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Office/Desk.usd",
        "secondary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Medical/Centrifuge.usd",
        "secondary_offset": (0.0, -1.8, 0.75),
        "checkpoint": {"name": "기기실-2", "x": 0.0, "y": -1.2, "radius": 0.35},
        "sample_items": ["나노드롭", "마이크로플레이트 리더", "마이크로 원심분리기", "전기영동 장치"],
    },
    {
        "name": "세포배양실",
        "category": "EQUIPMENT",
        "color": (0.15, 0.75, 0.4),  # 에메랄드 그린
        "pos": (2.0, -1.8, 0.0),
        "rot_z": 0.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Office/Desk.usd",
        "secondary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Medical/Biohazard_Trash.usd",
        "secondary_offset": (2.5, -1.8, 0.0),
        "checkpoint": {"name": "세포배양실", "x": 2.0, "y": -1.2, "radius": 0.35},
        "sample_items": ["도립현미경", "CO2 incubator", "생물안전작업대"],
    },
    {
        "name": "시약보관실",
        "category": "REAGENT",
        "color": (0.9, 0.55, 0.1),  # 앰버 오렌지
        "pos": (2.8, -0.2, 0.0),
        "rot_z": -90.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Medical/Medical_Cabinet.usd",
        "checkpoint": {"name": "시약보관실", "x": 2.2, "y": -0.2, "radius": 0.35},
        "sample_items": ["PBS", "TAE buffer", "TBE buffer", "Agarose", "pH meter"],
    },
    {
        "name": "냉장보관실",
        "category": "REAGENT",
        "color": (0.2, 0.7, 0.95),  # 아이스 블루
        "pos": (2.8, 1.2, 0.0),
        "rot_z": -90.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Office/Bookshelf.usd",
        "checkpoint": {"name": "냉장보관실", "x": 2.2, "y": 1.2, "radius": 0.35},
        "sample_items": ["DNA extraction kit"],
    },
    {
        "name": "냉동보관실",
        "category": "REAGENT",
        "color": (0.6, 0.3, 0.9),   # 딥 바이올렛
        "pos": (1.0, 2.0, 0.0),
        "rot_z": 180.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Office/Cabinet.usd",
        "checkpoint": {"name": "냉동보관실", "x": 1.0, "y": 1.4, "radius": 0.35},
        "sample_items": ["DNA ladder", "PCR master mix", "qPCR master mix", "RNA extraction kit"],
    },
    {
        "name": "일반실험실",
        "category": "EQUIPMENT",
        "color": (0.5, 0.55, 0.6),  # 메탈릭 그레이
        "pos": (-1.0, 2.0, 0.0),
        "rot_z": 180.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Medical/Surgical_Trolley.usd",
        "secondary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Medical/Mayo_Stand.usd",
        "secondary_offset": (-1.6, 2.0, 0.0),
        "checkpoint": {"name": "일반실험실", "x": -1.0, "y": 1.4, "radius": 0.35},
        "sample_items": ["일반 incubator", "Autoclave"],
    },
    {
        "name": "소모품보관실",
        "category": "CONSUMABLE",
        "color": (0.95, 0.75, 0.2), # 웜 옐로우
        "pos": (-2.8, 1.2, 0.0),
        "rot_z": 90.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Office/Bookshelf.usd",
        "checkpoint": {"name": "소모품보관실", "x": -2.2, "y": 1.2, "radius": 0.35},
        "sample_items": ["마이크로피펫 팁", "원심관", "페트리디쉬"],
    },
    {
        "name": "안전장비함",
        "category": "SAFETY",
        "color": (0.9, 0.15, 0.15),  # 세이프티 레드
        "pos": (-2.8, -0.2, 0.0),
        "rot_z": 90.0,
        "primary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/FireExtinguisher/fire_extinguisher.usd",
        "secondary_asset": NUCLEUS_ASSETS_ROOT + "/Isaac/Props/Safety_Glasses/safety_glasses.usd",
        "secondary_offset": (-2.8, -0.6, 0.5),
        "checkpoint": {"name": "안전장비함", "x": -2.2, "y": -0.2, "radius": 0.35},
        "sample_items": ["실험복", "보호안경", "내화학 장갑"],
    },
]

# ── 9개 구역을 순회하는 완벽한 메인 루프 순찰 트랙 (m 단위 좌표) ───
LAB_TRACK_POINTS_M = [
    (-2.0, -1.2),  # 기기실-1 앞
    (0.0, -1.2),   # 기기실-2 앞
    (2.0, -1.2),   # 세포배양실 앞
    (2.2, -0.2),   # 시약보관실 앞
    (2.2, 1.2),    # 냉장보관실 앞
    (1.0, 1.4),    # 냉동보관실 앞
    (-1.0, 1.4),   # 일반실험실 앞
    (-2.2, 1.2),   # 소모품보관실 앞
    (-2.2, -0.2),  # 안전장비함 앞
    (-2.0, -1.2),  # 루프 완결 (시작점)
]


def get_all_checkpoints():
    """9개 구역의 체크포인트 목록을 반환한다."""
    return [z["checkpoint"] for z in LAB_ZONES]


def build_lab_environment(stage):
    """Isaac Sim USD 스테이지에 고품질 3D 연구실 가구, 기구, 벽체, 조명 및 자율주행 트랙을 구축한다."""
    print("[LabWorld] Building High-Fidelity Realistic Laboratory Digital Twin...")

    # 1. 자연스러운 천장 및 돔 조명 (스마트 랩 면광원 시스템)
    dome_light_path = "/World/LabDomeLight"
    if not stage.GetPrimAtPath(dome_light_path).IsValid():
        dome_light = UsdLux.DomeLight.Define(stage, dome_light_path)
        dome_light.GetIntensityAttr().Set(2000.0)
        dome_light.GetColorAttr().Set(Gf.Vec3f(0.96, 0.98, 1.0))

    # 천장 LED 패널 라이트 4개 배치 (실제 실험실 분위기 연출)
    ceiling_lights = [
        (-1.5, -1.0, 2.8),
        (1.5, -1.0, 2.8),
        (-1.5, 1.0, 2.8),
        (1.5, 1.0, 2.8),
    ]
    for idx, (lx, ly, lz) in enumerate(ceiling_lights):
        lpath = f"/World/CeilingLights/Light_{idx}"
        if not stage.GetPrimAtPath(lpath).IsValid():
            rlight = UsdLux.RectLight.Define(stage, lpath)
            xform = UsdGeom.Xformable(rlight.GetPrim())
            xform.ClearXformOpOrder()
            xform.AddTranslateOp().Set(Gf.Vec3d(lx, ly, lz))
            xform.AddRotateXOp().Set(180.0)  # 아래쪽으로 비춤
            rlight.GetWidthAttr().Set(1.2)
            rlight.GetHeightAttr().Set(0.6)
            rlight.GetIntensityAttr().Set(3500.0)
            rlight.GetColorAttr().Set(Gf.Vec3f(0.98, 1.0, 1.0))

    # 2. 클린룸 연구실 바닥 & 외곽 벽체 생성
    floor_prim = stage.DefinePrim("/World/LabFloor", "Cube")
    floor_xform = UsdGeom.Xformable(floor_prim)
    floor_xform.ClearXformOpOrder()
    floor_xform.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, -0.01))
    floor_xform.AddScaleOp().Set(Gf.Vec3d(3.8, 3.0, 0.01))  # 7.6m x 6m 실험실 바닥
    UsdGeom.Gprim(floor_prim).GetDisplayColorAttr().Set([Gf.Vec3f(0.85, 0.88, 0.92)])  # 청결한 에폭시 타일색

    # 외곽 벽체 (세련된 라이트 그레이)
    walls_def = [
        (0.0, -2.6, 1.2, 3.8, 0.05, 1.2),  # 남측 벽
        (0.0, 2.6, 1.2, 3.8, 0.05, 1.2),   # 북측 벽
        (-3.6, 0.0, 1.2, 0.05, 2.6, 1.2),  # 서측 벽
        (3.6, 0.0, 1.2, 0.05, 2.6, 1.2),   # 동측 벽
    ]
    for idx, (wx, wy, wz, sx, sy, sz) in enumerate(walls_def):
        wpath = f"/World/Walls/Wall_{idx}"
        wprim = stage.DefinePrim(wpath, "Cube")
        wxform = UsdGeom.Xformable(wprim)
        wxform.ClearXformOpOrder()
        wxform.AddTranslateOp().Set(Gf.Vec3d(wx, wy, wz))
        wxform.AddScaleOp().Set(Gf.Vec3d(sx, sy, sz))
        UsdGeom.Gprim(wprim).GetDisplayColorAttr().Set([Gf.Vec3f(0.92, 0.93, 0.95)])

    # 3. 9개 구역 실사 3D 에셋 및 가구 배치
    for idx, zone in enumerate(LAB_ZONES):
        pos = zone["pos"]
        rot_z = zone.get("rot_z", 0.0)

        # A. 메인 3D 기구/가구 에셋 참조 로드
        primary_path = f"/World/Zones/Zone_{idx}_Primary"
        prim = stage.DefinePrim(primary_path, "Xform")
        prim.GetReferences().AddReference(zone["primary_asset"])
        xform = UsdGeom.Xformable(prim)
        xform.ClearXformOpOrder()
        xform.AddTranslateOp().Set(Gf.Vec3d(pos[0], pos[1], pos[2]))
        if rot_z != 0.0:
            xform.AddRotateZOp().Set(rot_z)

        # B. 보조 정밀 기기 에셋 (원심분리기, 소화기, 보호안경 등)이 있는 경우 추가 배치
        if "secondary_asset" in zone:
            sec_pos = zone["secondary_offset"]
            secondary_path = f"/World/Zones/Zone_{idx}_Secondary"
            sec_prim = stage.DefinePrim(secondary_path, "Xform")
            sec_prim.GetReferences().AddReference(zone["secondary_asset"])
            sec_xform = UsdGeom.Xformable(sec_prim)
            sec_xform.ClearXformOpOrder()
            sec_xform.AddTranslateOp().Set(Gf.Vec3d(sec_pos[0], sec_pos[1], sec_pos[2]))
            if rot_z != 0.0:
                sec_xform.AddRotateZOp().Set(rot_z)

        # C. 구역 대표 색상 안내 사이니지 기둥 (현대식 스마트 랩 표식)
        tag_path = f"/World/Signs/Sign_{idx}"
        tag_prim = stage.DefinePrim(tag_path, "Cube")
        tag_xform = UsdGeom.Xformable(tag_prim)
        tag_xform.ClearXformOpOrder()
        tag_xform.AddTranslateOp().Set(Gf.Vec3d(pos[0], pos[1], 1.2))
        tag_xform.AddScaleOp().Set(Gf.Vec3d(0.25, 0.05, 0.1))
        c = zone["color"]
        UsdGeom.Gprim(tag_prim).GetDisplayColorAttr().Set([Gf.Vec3f(c[0], c[1], c[2])])

        # D. 바닥 QR 체크포인트 유도 원형 패드 (스마트 바닥 센서)
        cp = zone["checkpoint"]
        cp_path = f"/World/Checkpoints/Pad_{idx}"
        cp_prim = stage.DefinePrim(cp_path, "Cylinder")
        cp_xform = UsdGeom.Xformable(cp_prim)
        cp_xform.ClearXformOpOrder()
        cp_xform.AddTranslateOp().Set(Gf.Vec3d(cp["x"], cp["y"], 0.003))
        cp_xform.AddScaleOp().Set(Gf.Vec3d(0.18, 0.18, 0.003))
        # 황금빛 테두리 + 구역 색상 포인트
        UsdGeom.Gprim(cp_prim).GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 0.8, 0.2)])

    # 4. 바닥 AGV 자율주행 라인트랙 시각화 (매립형 검정 테이프 라인)
    track_root_path = "/World/LineTrack"
    for i in range(len(LAB_TRACK_POINTS_M) - 1):
        p1 = LAB_TRACK_POINTS_M[i]
        p2 = LAB_TRACK_POINTS_M[i + 1]
        mx = (p1[0] + p2[0]) / 2.0
        my = (p1[1] + p2[1]) / 2.0
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        angle_deg = math.degrees(math.atan2(dy, dx))

        seg_path = f"{track_root_path}/Segment_{i}"
        seg_prim = stage.DefinePrim(seg_path, "Cube")
        seg_xform = UsdGeom.Xformable(seg_prim)
        seg_xform.ClearXformOpOrder()
        seg_xform.AddTranslateOp().Set(Gf.Vec3d(mx, my, 0.002))
        seg_xform.AddRotateZOp().Set(angle_deg)
        seg_xform.AddScaleOp().Set(Gf.Vec3d(length / 2.0, 0.025, 0.001))  # 5cm 폭 정밀 주행 라인
        UsdGeom.Gprim(seg_prim).GetDisplayColorAttr().Set([Gf.Vec3f(0.08, 0.08, 0.08)])

    print(f"[LabWorld] Realistic Smart Lab with 9 zones & {len(LAB_TRACK_POINTS_M)-1} patrol segments built successfully!")
