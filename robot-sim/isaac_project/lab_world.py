"""LabKeeper 가상 실험실 9대 구역 및 디지털 트윈 월드 빌더 (NVIDIA Isaac Sim).

LabKeeper의 9개 고정 보관 구역(기기실-1, 기기실-2, 세포배양실, 시약보관실,
냉장보관실, 냉동보관실, 일반실험실, 소모품보관실, 안전장비함)과
각 구역을 잇는 둘레 ~14m의 메인 순찰 라인트랙을 프로그래밍 방식으로 구축한다.
"""
import math
from pxr import Gf, UsdGeom, UsdLux

# ── LabKeeper 9개 보관 구역 정의 (Supabase items 테이블과 1:1 매칭) ───
LAB_ZONES = [
    {
        "name": "기기실-1",
        "category": "EQUIPMENT",
        "color": (0.2, 0.4, 0.8),  # 파랑
        "shelf_pos": (-2.0, -1.8, 0.4),
        "shelf_size": (0.8, 0.4, 0.8),
        "checkpoint": {"name": "기기실-1", "x": -2.0, "y": -1.2, "radius": 0.35},
        "sample_items": ["형광현미경", "일반 PCR 장비", "Real-time PCR 장비", "UV-Vis 분광광도계"],
    },
    {
        "name": "기기실-2",
        "category": "EQUIPMENT",
        "color": (0.2, 0.5, 0.7),
        "shelf_pos": (0.0, -1.8, 0.4),
        "shelf_size": (0.8, 0.4, 0.8),
        "checkpoint": {"name": "기기실-2", "x": 0.0, "y": -1.2, "radius": 0.35},
        "sample_items": ["나노드롭", "마이크로플레이트 리더", "마이크로 원심분리기", "전기영동 장치"],
    },
    {
        "name": "세포배양실",
        "category": "EQUIPMENT",
        "color": (0.3, 0.7, 0.4),  # 초록
        "shelf_pos": (2.0, -1.8, 0.4),
        "shelf_size": (0.8, 0.4, 0.8),
        "checkpoint": {"name": "세포배양실", "x": 2.0, "y": -1.2, "radius": 0.35},
        "sample_items": ["도립현미경", "CO2 incubator", "생물안전작업대"],
    },
    {
        "name": "시약보관실",
        "category": "REAGENT",
        "color": (0.8, 0.5, 0.2),  # 주황
        "shelf_pos": (2.8, -0.2, 0.4),
        "shelf_size": (0.4, 0.8, 0.8),
        "checkpoint": {"name": "시약보관실", "x": 2.2, "y": -0.2, "radius": 0.35},
        "sample_items": ["PBS", "TAE buffer", "TBE buffer", "Agarose", "pH meter"],
    },
    {
        "name": "냉장보관실",
        "category": "REAGENT",
        "color": (0.3, 0.7, 0.9),  # 하늘
        "shelf_pos": (2.8, 1.2, 0.4),
        "shelf_size": (0.4, 0.8, 0.8),
        "checkpoint": {"name": "냉장보관실", "x": 2.2, "y": 1.2, "radius": 0.35},
        "sample_items": ["DNA extraction kit"],
    },
    {
        "name": "냉동보관실",
        "category": "REAGENT",
        "color": (0.5, 0.3, 0.8),  # 보라
        "shelf_pos": (1.0, 2.0, 0.4),
        "shelf_size": (0.8, 0.4, 0.8),
        "checkpoint": {"name": "냉동보관실", "x": 1.0, "y": 1.4, "radius": 0.35},
        "sample_items": ["DNA ladder", "PCR master mix", "qPCR master mix", "RNA extraction kit"],
    },
    {
        "name": "일반실험실",
        "category": "EQUIPMENT",
        "color": (0.6, 0.6, 0.6),  # 회색
        "shelf_pos": (-1.0, 2.0, 0.4),
        "shelf_size": (0.8, 0.4, 0.8),
        "checkpoint": {"name": "일반실험실", "x": -1.0, "y": 1.4, "radius": 0.35},
        "sample_items": ["일반 incubator", "Autoclave"],
    },
    {
        "name": "소모품보관실",
        "category": "CONSUMABLE",
        "color": (0.9, 0.7, 0.2),  # 황금
        "shelf_pos": (-2.8, 1.2, 0.4),
        "shelf_size": (0.4, 0.8, 0.8),
        "checkpoint": {"name": "소모품보관실", "x": -2.2, "y": 1.2, "radius": 0.35},
        "sample_items": ["마이크로피펫 팁", "원심관", "페트리디쉬"],
    },
    {
        "name": "안전장비함",
        "category": "SAFETY",
        "color": (0.9, 0.2, 0.2),  # 빨강
        "shelf_pos": (-2.8, -0.2, 0.4),
        "shelf_size": (0.4, 0.8, 0.8),
        "checkpoint": {"name": "안전장비함", "x": -2.2, "y": -0.2, "radius": 0.35},
        "sample_items": ["실험복", "보호안경", "내화학 장갑"],
    },
]

# ── 9개 구역을 순회하는 완벽한 메인 루프 순찰 트랙 (m 단위 좌표) ───
LAB_TRACK_POINTS_M = [
    (-2.2, -1.2),  # 기기실-1 앞
    (0.0, -1.2),   # 기기실-2 앞
    (2.2, -1.2),   # 세포배양실 앞
    (2.2, -0.2),   # 시약보관실 앞
    (2.2, 1.4),    # 냉장보관실 앞
    (1.0, 1.4),    # 냉동보관실 앞
    (-1.0, 1.4),   # 일반실험실 앞
    (-2.2, 1.4),   # 소모품보관실 앞
    (-2.2, -0.2),  # 안전장비함 앞
    (-2.2, -1.2),  # 루프 완결 (시작점)
]


def get_all_checkpoints():
    """9개 구역의 체크포인트 목록을 반환한다."""
    return [z["checkpoint"] for z in LAB_ZONES]


def build_lab_environment(stage):
    """Isaac Sim USD 스테이지에 연구실 9개 보관 선반, 바닥 라인트랙, 조명을 생성한다."""
    print("[LabWorld] Building LabKeeper 9 Storage Zones digital twin...")

    # 1. 돔 라이트 (실험실 전체 밝은 환경 조명)
    dome_light_path = "/World/LabDomeLight"
    if not stage.GetPrimAtPath(dome_light_path).IsValid():
        dome_light = UsdLux.DomeLight.Define(stage, dome_light_path)
        dome_light.GetIntensityAttr().Set(1500.0)
        dome_light.GetColorAttr().Set(Gf.Vec3f(0.95, 0.98, 1.0))

    # 2. 9개 구역 선반 및 라벨 큐브 생성
    for idx, zone in enumerate(LAB_ZONES):
        shelf_path = f"/World/Shelves/Zone_{idx}"
        shelf_prim = stage.DefinePrim(shelf_path, "Cube")
        xform = UsdGeom.Xformable(shelf_prim)
        xform.ClearXformOpOrder()

        pos = zone["shelf_pos"]
        size = zone["shelf_size"]
        xform.AddTranslateOp().Set(Gf.Vec3d(pos[0], pos[1], pos[2]))
        xform.AddScaleOp().Set(Gf.Vec3d(size[0] / 2.0, size[1] / 2.0, size[2] / 2.0))

        # 구역별 색상 지정
        color = zone["color"]
        gprim = UsdGeom.Gprim(shelf_prim)
        gprim.GetDisplayColorAttr().Set([Gf.Vec3f(color[0], color[1], color[2])])

        # 선반 위 물품 QR 체크포인트 시각 마커 (작은 황금색 원통)
        cp = zone["checkpoint"]
        cp_marker_path = f"/World/Checkpoints/Marker_{idx}"
        cp_prim = stage.DefinePrim(cp_marker_path, "Cylinder")
        cp_xform = UsdGeom.Xformable(cp_prim)
        cp_xform.ClearXformOpOrder()
        cp_xform.AddTranslateOp().Set(Gf.Vec3d(cp["x"], cp["y"], 0.01))
        cp_xform.AddScaleOp().Set(Gf.Vec3d(0.12, 0.12, 0.005))
        UsdGeom.Gprim(cp_prim).GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 0.85, 0.2)])

    # 3. 바닥 순찰 라인트랙 시각화 (각 구간을 잇는 얇은 검은색 테이프 라인 생성)
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
        seg_xform.AddScaleOp().Set(Gf.Vec3d(length / 2.0, 0.02, 0.001))  # 4cm 너비 라인
        UsdGeom.Gprim(seg_prim).GetDisplayColorAttr().Set([Gf.Vec3f(0.1, 0.1, 0.1)])

    print(f"[LabWorld] 9 Storage Zones and {len(LAB_TRACK_POINTS_M)-1} patrol segments built successfully!")
