// LabBot - 물품 목록 데이터
// TODO: Supabase 물품 테이블에서 실시간으로 불러오는 방식으로 교체할 것
// (지금은 localStorage에 저장된 데이터를 사용하고, 없으면 아래 기본 예시 데이터로 초기화)

const LAB_ITEMS_STORAGE_KEY = "labbot_items";

const LAB_CATEGORIES = [
  { key: "all", label: "전체" },
  { key: "optical", label: "광학기기" },
  { key: "separation", label: "분리기기" },
  { key: "measurement", label: "측정기기" },
  { key: "consumable", label: "소모품" },
  { key: "safety", label: "안전장비" },
];

const LAB_ITEMS_DEFAULT = [
  { id: "mic-a", name: "현미경 A", category: "optical", categoryLabel: "광학기기", location: "3층 실험실 A", available: 2, total: 3 },
  { id: "mic-b", name: "형광현미경 B", category: "optical", categoryLabel: "광학기기", location: "3층 실험실 A", available: 0, total: 1 },
  { id: "centrifuge", name: "원심분리기", category: "separation", categoryLabel: "분리기기", location: "2층 실험실 B", available: 0, total: 1 },
  { id: "shaker", name: "진탕배양기", category: "separation", categoryLabel: "분리기기", location: "2층 실험실 B", available: 1, total: 2 },
  { id: "scale", name: "전자저울", category: "measurement", categoryLabel: "측정기기", location: "2층 실험실 C", available: 3, total: 3 },
  { id: "ph-meter", name: "pH미터", category: "measurement", categoryLabel: "측정기기", location: "2층 실험실 C", available: 1, total: 2 },
  { id: "pipette-set", name: "피펫 세트", category: "consumable", categoryLabel: "소모품", location: "3층 실험실 A", available: 5, total: 6 },
  { id: "test-tube-set", name: "시험관 세트", category: "consumable", categoryLabel: "소모품", location: "3층 실험실 A", available: 8, total: 10 },
  { id: "goggles", name: "안전고글 세트", category: "safety", categoryLabel: "안전장비", location: "1층 안전관리실", available: 10, total: 10 },
  { id: "lab-gown", name: "실험용 가운", category: "safety", categoryLabel: "안전장비", location: "1층 안전관리실", available: 4, total: 8 },
];

function loadLabItems() {
  try {
    const raw = localStorage.getItem(LAB_ITEMS_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) {
    // 저장된 데이터가 손상된 경우 기본값으로 대체
  }
  return LAB_ITEMS_DEFAULT.map((item) => ({ ...item }));
}

function saveLabItems(items) {
  localStorage.setItem(LAB_ITEMS_STORAGE_KEY, JSON.stringify(items));
}

let LAB_ITEMS = loadLabItems();
