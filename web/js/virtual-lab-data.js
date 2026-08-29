// LabBot - 가상 생명공학 실험실 디지털 트윈 매핑 데이터
// 핵심 원칙:
// 1. 물품명이나 재고 수량, 비밀 QR 코드는 여기에 하드코딩하지 않는다.
// 2. sceneObjectId와 Supabase items의 연결 키(itemId 또는 itemQuery)만 정의한다.
// 3. 실제 수량, 상태, 위치, 유효기간은 Supabase items 테이블에서 동적으로 조회한다.
// 4. 환경 연출 객체(실험대, 싱크대, 벽, 문 등)와 디지털 트윈 재고 물품을 엄격히 분리한다.

const VIRTUAL_LAB_ROOMS = [
  { id: "all", name: "전체 연구실", code: "ALL" },
  { id: "일반실험실", name: "일반실험실", code: "GEN" },
  { id: "기기실-1", name: "기기실-1 (분석/PCR)", code: "EQ1" },
  { id: "기기실-2", name: "기기실-2 (원심/저울)", code: "EQ2" },
  { id: "세포배양실", name: "세포배양실 (BSC/인큐베이터)", code: "CELL" },
  { id: "시약보관실", name: "시약보관실 (안전캐비닛)", code: "REAG" },
  { id: "냉장보관실", name: "냉장보관실 (4℃)", code: "COLD" },
  { id: "냉동보관실", name: "냉동보관실 (-80℃/-20℃)", code: "FRZ" },
  { id: "소모품보관실", name: "소모품보관실", code: "CON" },
  { id: "안전장비함", name: "안전장비구역 (소화기/세안대)", code: "SAF" },
];

// 1단계 대표 물품 매핑 (디지털 트윈 객체)
const VIRTUAL_LAB_OBJECTS = [
  {
    sceneObjectId: "eq-pipette-01",
    label: "EQ-01",
    displayNameFallback: "마이크로피펫 세트",
    category: "EQUIPMENT",
    room: "기기실-2",
    zoneTag: "일반실험실/기기실",
    position: { x: 38, y: 62 }, // 퍼센트 좌표 (반응형 2.5D 뷰)
    displayMode: "single",
    itemQuery: "마이크로피펫",
    iconType: "pipette",
    description: "정밀 액체 분주용 마이크로피펫 (0.5~1000uL)"
  },
  {
    sceneObjectId: "con-tips-01",
    label: "CON-01",
    displayNameFallback: "피펫 팁",
    category: "CONSUMABLE",
    room: "소모품보관실",
    zoneTag: "소모품실 선반",
    position: { x: 80, y: 72 },
    displayMode: "grouped",
    itemQuery: "팁",
    iconType: "tips",
    description: "멸균 필터 피펫 팁 (200uL / 1000uL)"
  },
  {
    sceneObjectId: "eq-centrifuge-01",
    label: "EQ-02",
    displayNameFallback: "마이크로 원심분리기",
    category: "EQUIPMENT",
    room: "기기실-2",
    zoneTag: "기기실-2 벤치",
    position: { x: 26, y: 58 },
    displayMode: "single",
    itemQuery: "원심분리기",
    iconType: "centrifuge",
    description: "고속 샘플 분리용 마이크로 원심분리기"
  },
  {
    sceneObjectId: "eq-scale-01",
    label: "EQ-03",
    displayNameFallback: "정밀 전자저울",
    category: "EQUIPMENT",
    room: "기기실-2",
    zoneTag: "기기실-2 벤치",
    position: { x: 32, y: 54 },
    displayMode: "single",
    itemQuery: "전자저울",
    iconType: "scale",
    description: "시약 정밀 칭량용 4단 전자저울"
  },
  {
    sceneObjectId: "eq-phmeter-01",
    label: "EQ-04",
    displayNameFallback: "pH meter",
    category: "EQUIPMENT",
    room: "시약보관실",
    zoneTag: "시약 조제대",
    position: { x: 50, y: 55 },
    displayMode: "single",
    itemQuery: "pH",
    iconType: "phmeter",
    description: "완충용액 pH 정밀 측정기"
  },
  {
    sceneObjectId: "eq-microscope-01",
    label: "EQ-05",
    displayNameFallback: "형광 / 위상차 현미경",
    category: "EQUIPMENT",
    room: "기기실-1",
    zoneTag: "기기실-1 광학대",
    position: { x: 68, y: 52 },
    displayMode: "single",
    itemQuery: "현미경",
    iconType: "microscope",
    description: "세포 및 조직 관찰용 광학/형광현미경"
  },
  {
    sceneObjectId: "eq-pcr-01",
    label: "EQ-06",
    displayNameFallback: "PCR 증폭기 (Thermal Cycler)",
    category: "EQUIPMENT",
    room: "기기실-1",
    zoneTag: "기기실-1 PCR 벤치",
    position: { x: 74, y: 48 },
    displayMode: "single",
    itemQuery: "PCR",
    iconType: "pcr",
    description: "유전자 증폭 및 실시간 분석 시스템"
  },
  {
    sceneObjectId: "eq-freezer-01",
    label: "EQ-07",
    displayNameFallback: "초저온 냉동고 (-80℃)",
    category: "EQUIPMENT",
    room: "냉동보관실",
    zoneTag: "냉동보관실 A열",
    position: { x: 14, y: 35 },
    displayMode: "single",
    itemQuery: "냉동고",
    iconType: "freezer",
    description: "세포주 및 핵산 장기 보존용 -80℃ Deep Freezer"
  },
  {
    sceneObjectId: "reagent-ethanol-01",
    label: "R-01",
    displayNameFallback: "무수 에탄올 / 유기용매",
    category: "REAGENT",
    room: "시약보관실",
    zoneTag: "노란색 안전캐비닛(Solvents)",
    position: { x: 54, y: 38 },
    displayMode: "grouped",
    itemQuery: "에탄올",
    iconType: "reagent",
    description: "인화성 시약 전용 닫힌 안전 방화 캐비닛"
  },
  {
    sceneObjectId: "saf-extinguisher-01",
    label: "SAF-01",
    displayNameFallback: "소화기 & 비상 세안기",
    category: "SAFETY",
    room: "안전장비함",
    zoneTag: "연구실 출입문 안전구역",
    position: { x: 88, y: 35 },
    displayMode: "single",
    itemQuery: "소화기",
    iconType: "safety",
    description: "ABC 분말 소화기 및 안구 세척 비상 세안대"
  },
  {
    sceneObjectId: "saf-biohazard-01",
    label: "SAF-02",
    displayNameFallback: "생물학적 / 샤프 폐기물통",
    category: "SAFETY",
    room: "일반실험실",
    zoneTag: "실험대 하단 폐기구역",
    position: { x: 44, y: 76 },
    displayMode: "single",
    itemQuery: "장갑",
    iconType: "waste",
    description: "주사바늘/팁 전용 샤프통 및 Biohazard 멸균 폐기함"
  }
];

// 순수 환경 연출 객체 (DB 물품이 아닌 가구/구조물)
const VIRTUAL_LAB_ENVIRONMENT_PROPS = [
  { type: "workbench", name: "중앙 메인 실험대", position: { x: 40, y: 60 }, width: 35, height: 18 },
  { type: "glass_wall", name: "기기실 유리 파티션", position: { x: 62, y: 20 }, width: 2, height: 40 },
  { type: "glass_wall", name: "세포배양실 클린 유리벽", position: { x: 30, y: 20 }, width: 2, height: 40 },
  { type: "safety_cabinet", name: "인화성 물질 안전 캐비닛 (닫힘)", position: { x: 54, y: 32 }, width: 8, height: 14 },
  { type: "fume_hood", name: "흄후드 (배기장치)", position: { x: 44, y: 25 }, width: 10, height: 12 },
  { type: "clean_bench", name: "BSC 생물안전작업대", position: { x: 22, y: 25 }, width: 10, height: 12 }
];

// robot-sim/isaac_project/scene/guide_targets.json의 실제 이동 좌표를 웹 조감도 좌표로
// 정규화한 데이터다. 웹이 임의의 길을 그리지 않고 시뮬레이터와 같은 체크포인트를
// 사용하도록 sceneObjectId별 목적지와 경유점을 함께 보관한다.
const VIRTUAL_LAB_GUIDE_ROUTES = {
  "eq-pipette-01": [[0, 0], [0, 4], [1.8, 4], [2.6, 5.55]],
  "con-tips-01": [[0, 0], [0, 4], [1.8, 4], [1.8, 10]],
  "eq-centrifuge-01": [[0, 0], [0, 4], [1.8, 4], [2.6, 2.35]],
  "eq-scale-01": [[0, 0], [0, 4], [-1.8, 4], [-2.6, 5.72]],
  "eq-microscope-01": [[0, 0], [0, 4], [-1.8, 4], [-2.35, 2.1]],
  "eq-pcr-01": [[0, 0], [0, 4], [-1.8, 4], [-1.8, 10]],
  "eq-phmeter-01": [[0, 0], [0, 4], [-1.8, 4], [-1.8, 12.4], [0, 13.6]],
  "eq-freezer-01": [[0, 0], [0, 4], [1.8, 4], [1.8, 12.4], [1.8, 14.6]],
  "reagent-ethanol-01": [[0, 0], [0, 4], [-1.8, 4], [-1.8, 12.4], [0, 13.6]],
  "saf-extinguisher-01": [[0, 0]]
};

// build_lab_asset.py와 object_bindings.json에서 가져온 실제 Isaac 월드 XY 좌표.
// route의 마지막 점은 로봇 정지점이고, 아래 좌표는 물품 prim이 놓인 위치라 서로 다르다.
const VIRTUAL_LAB_OBJECT_WORLD_POSITIONS = {
  "eq-pipette-01": [3.64, 5.55],
  "con-tips-01": [3.30, 6.65],
  "eq-centrifuge-01": [3.66, 2.35],
  "eq-scale-01": [-3.65, 5.72],
  "eq-phmeter-01": [-1.28, 15.25],
  "eq-microscope-01": [-3.62, 2.10],
  "eq-pcr-01": [-5.55, 10.65],
  "eq-freezer-01": [5.02, 12.82],
  "reagent-ethanol-01": [6.18, 14.93],
  "saf-extinguisher-01": [5.95, -1.25],
  "saf-biohazard-01": [4.55, -1.18]
};

// Isaac 장면의 14m × 18m 바닥과 주요 충돌 가구를 위에서 본 직사각형으로 투영한다.
const VIRTUAL_LAB_SIM_GEOMETRY = {
  bounds: { minX: -7, maxX: 7, minY: -2, maxY: 16 },
  fixtures: [
    { id: "corridor", label: "ROBOT AISLE", x: 0, y: 7, w: 4.75, h: 17.4, type: "aisle" },
    { id: "island-west", label: "Island West", x: -3.65, y: 4.25, w: 1.25, h: 7.4, type: "bench" },
    { id: "island-east", label: "Island East", x: 3.65, y: 4.25, w: 1.25, h: 7.4, type: "bench" },
    { id: "wall-west", label: "West Wall Bench", x: -6.25, y: 4.15, w: 0.72, h: 8, type: "bench" },
    { id: "wall-east", label: "East Wall Bench", x: 6.25, y: 4.15, w: 0.72, h: 8, type: "bench" },
    { id: "inst-1", label: "Instrument Bench 1", x: -4.65, y: 10.65, w: 3.3, h: 0.72, type: "equipment" },
    { id: "inst-2", label: "Instrument Bench 2", x: -4.65, y: 12.65, w: 3.3, h: 0.72, type: "equipment" },
    { id: "cell-bsc", label: "BSC", x: -4.55, y: 14.85, w: 2.65, h: 0.78, type: "equipment" },
    { id: "consumables-1", label: "Consumables 1", x: 3.45, y: 11.06, w: 1.42, h: 0.56, type: "storage" },
    { id: "consumables-2", label: "Consumables 2", x: 5.25, y: 11.06, w: 1.42, h: 0.56, type: "storage" },
    { id: "fridge", label: "4℃", x: 3.65, y: 12.82, w: 1.08, h: 0.82, type: "cold" },
    { id: "freezer-1", label: "-80℃ 1", x: 5.02, y: 12.82, w: 1.08, h: 0.82, type: "cold" },
    { id: "freezer-2", label: "-80℃ 2", x: 6.15, y: 12.82, w: 1.08, h: 0.82, type: "cold" },
    { id: "reagent", label: "Reagent Desk", x: 0, y: 15.28, w: 3.8, h: 0.78, type: "reagent" },
    { id: "flammable", label: "Flammable", x: 6.18, y: 14.93, w: 0.85, h: 0.72, type: "safety" },
    { id: "ppe", label: "PPE", x: -6.20, y: -0.75, w: 0.88, h: 0.66, type: "safety" }
  ],
  partitions: [
    { x: -2.48, y: 10.23, w: 0.10, h: 2.42 }, { x: 2.48, y: 10.23, w: 0.10, h: 2.42 },
    { x: -2.48, y: 12.70, w: 0.10, h: 2.28 }, { x: 2.48, y: 12.70, w: 0.10, h: 2.28 },
    { x: -2.48, y: 14.94, w: 0.10, h: 1.96 }, { x: 2.48, y: 14.94, w: 0.10, h: 1.96 },
    { x: -4.73, y: 11.50, w: 4.40, h: 0.12 }, { x: 4.73, y: 11.50, w: 4.40, h: 0.12 },
    { x: -4.73, y: 13.90, w: 4.40, h: 0.12 }, { x: 4.73, y: 13.90, w: 4.40, h: 0.12 }
  ]
};

// Isaac Sim 실험실의 기능 구역을 2D 운영 조감도로 단순화한 배치다. 좌표는 화면상의
// 퍼센트이며 재고나 물품명은 포함하지 않는다. 실제 물품은 Supabase와 위 객체 매핑에서
// 계속 가져온다.
const VIRTUAL_LAB_ROOM_LAYOUTS = [
  { id: "기기실-1", code: "ZONE A", label: "분석 · PCR", x: 2, y: 3, w: 30, h: 28 },
  { id: "시약보관실", code: "ZONE B", label: "시약 조제 · 보관", x: 34, y: 3, w: 30, h: 28 },
  { id: "냉동보관실", code: "ZONE C", label: "-80℃ / -20℃", x: 66, y: 3, w: 32, h: 28 },
  { id: "일반실험실", code: "ZONE D", label: "중앙 실험대", x: 2, y: 35, w: 38, h: 28 },
  { id: "기기실-2", code: "ZONE E", label: "원심 · 계측", x: 42, y: 35, w: 30, h: 28 },
  { id: "세포배양실", code: "ZONE F", label: "BSC · 배양", x: 74, y: 35, w: 24, h: 28 },
  { id: "소모품보관실", code: "ZONE G", label: "소모품 선반", x: 2, y: 67, w: 30, h: 28 },
  { id: "냉장보관실", code: "ZONE H", label: "4℃ 냉장", x: 34, y: 67, w: 30, h: 28 },
  { id: "안전장비함", code: "ZONE I", label: "안전장비 · Raspbot Dock", x: 66, y: 67, w: 32, h: 28 }
];

window.VIRTUAL_LAB_ROOMS = VIRTUAL_LAB_ROOMS;
window.VIRTUAL_LAB_OBJECTS = VIRTUAL_LAB_OBJECTS;
window.VIRTUAL_LAB_ENVIRONMENT_PROPS = VIRTUAL_LAB_ENVIRONMENT_PROPS;
window.VIRTUAL_LAB_GUIDE_ROUTES = VIRTUAL_LAB_GUIDE_ROUTES;
window.VIRTUAL_LAB_ROOM_LAYOUTS = VIRTUAL_LAB_ROOM_LAYOUTS;
window.VIRTUAL_LAB_OBJECT_WORLD_POSITIONS = VIRTUAL_LAB_OBJECT_WORLD_POSITIONS;
window.VIRTUAL_LAB_SIM_GEOMETRY = VIRTUAL_LAB_SIM_GEOMETRY;
