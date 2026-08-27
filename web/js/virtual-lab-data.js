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

window.VIRTUAL_LAB_ROOMS = VIRTUAL_LAB_ROOMS;
window.VIRTUAL_LAB_OBJECTS = VIRTUAL_LAB_OBJECTS;
window.VIRTUAL_LAB_ENVIRONMENT_PROPS = VIRTUAL_LAB_ENVIRONMENT_PROPS;
