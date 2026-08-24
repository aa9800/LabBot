// LabBot - 물품 데이터 (Supabase items 테이블 연동)
// 등록/검색/재고수정/삭제 규칙은 web/docs/labbot_schema.sql의 items 테이블 + 제약조건이 최종 근거.

// 생명공학 실험실 물품 유형 — items.item_type/category 값과 그대로 맞춘다
// (예전엔 광학/분리/측정기기로 나눴었는데, 실제 물품 데이터를 생명공학 실험실
// 기준으로 바꾸면서 장비/시약/소모품/PPE/안전물품 5종으로 단순화했다)
const LAB_CATEGORIES = [
  { key: "all", label: "전체" },
  { key: "EQUIPMENT", label: "장비" },
  { key: "REAGENT", label: "시약" },
  { key: "CONSUMABLE", label: "소모품" },
  { key: "PPE", label: "PPE" },
  { key: "SAFETY", label: "안전물품" },
];

// ---------- 재고 상태 계산 (공통 함수 — 여러 파일에 흩어놓지 않고 여기 한 곳에만 둔다) ----------
//
// manual_status: DB에 저장되는 "관리자가 직접 정하는" 값. 지금은 null 또는 'MAINTENANCE'만 쓴다.
// 나머지 상태(OUT_OF_STOCK/LOW_STOCK/EXPIRED/EXPIRING_SOON/AVAILABLE)는 저장하지 않고
// available_qty/minimum_qty/expires_at을 기준으로 매번 새로 계산한다 — DB 값을 그대로
// 믿으면 날짜가 지나도 상태가 안 바뀌는 문제가 생기기 때문이다.
const STOCK_STATUS_LABEL = {
  AVAILABLE: "대여 가능",
  LOW_STOCK: "재고 부족",
  OUT_OF_STOCK: "품절",
  EXPIRING_SOON: "유효기간 임박",
  EXPIRED: "유효기간 만료",
  MAINTENANCE: "점검 중",
};

const STOCK_STATUS_BADGE_CLASS = {
  AVAILABLE: "badge-available",
  LOW_STOCK: "badge-sev-medium",
  OUT_OF_STOCK: "badge-sev-high",
  EXPIRING_SOON: "badge-sev-medium",
  EXPIRED: "badge-sev-high",
  MAINTENANCE: "badge-inuse",
};

// 이 상태들은 재고/유효기간 문제가 있어도 "경고만" — 대여 자체는 막지 않는다.
// MAINTENANCE / EXPIRED / OUT_OF_STOCK만 실제로 대여를 막는다.
const NON_RENTABLE_STATUSES = new Set(["MAINTENANCE", "EXPIRED", "OUT_OF_STOCK"]);

function computeStockStatus(item) {
  if (item.manual_status === "MAINTENANCE") {
    return "MAINTENANCE";
  }

  if (item.expires_at) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const expirationDate = new Date(`${item.expires_at}T00:00:00`);

    if (expirationDate < today) {
      return "EXPIRED";
    }

    const thirtyDaysLater = new Date(today);
    thirtyDaysLater.setDate(thirtyDaysLater.getDate() + 30);
    if (expirationDate <= thirtyDaysLater) {
      return "EXPIRING_SOON";
    }
  }

  if (item.available_qty === 0) {
    return "OUT_OF_STOCK";
  }

  if (
    item.minimum_qty !== null &&
    item.minimum_qty !== undefined &&
    item.available_qty <= item.minimum_qty
  ) {
    return "LOW_STOCK";
  }

  return "AVAILABLE";
}

// 대여 가능 여부도 여기서만 판단한다 — items.js 등 다른 파일이 각자 다시 계산하지 않는다.
function canRentItem(item) {
  return !NON_RENTABLE_STATUSES.has(computeStockStatus(item));
}

function categoryLabelOf(key) {
  const found = LAB_CATEGORIES.find((c) => c.key === key);
  return found ? found.label : key;
}

// 검색: 이름 부분일치 + category/location 필터를 동시에(AND) 적용
async function searchItems({ name = "", category = "all", location = "all" } = {}) {
  let query = supabaseClient.from("items").select("*").order("name", { ascending: true });

  const trimmedName = name.trim();
  if (trimmedName) {
    query = query.ilike("name", `%${trimmedName}%`);
  }
  if (category && category !== "all") {
    query = query.eq("category", category);
  }
  if (location && location !== "all") {
    query = query.eq("location", location);
  }

  const { data, error } = await query;
  if (error) throw error;

  return data.map((item) => ({ ...item, categoryLabel: categoryLabelOf(item.category) }));
}

async function fetchItemById(id) {
  const { data, error } = await supabaseClient.from("items").select("*").eq("id", id).single();
  if (error) throw error;
  return { ...data, categoryLabel: categoryLabelOf(data.category) };
}

// 검색/필터용 위치 목록 (현재 등록된 물품 기준 중복제거)
async function fetchLocations() {
  const { data, error } = await supabaseClient.from("items").select("location");
  if (error) throw error;
  return [...new Set(data.map((row) => row.location))].sort();
}

// 등록: qr_code는 DB 트리거가 서버에서 랜덤 발급, available_qty는 total_qty로 시작
async function createItem({ name, category, location, total_qty }) {
  const { data, error } = await supabaseClient
    .from("items")
    .insert({ name, category, location, total_qty, available_qty: total_qty })
    .select()
    .single();

  if (error) throw error;
  return { ...data, categoryLabel: categoryLabelOf(data.category) };
}

// 재고 수정: available_qty <= total_qty를 항상 유지 (DB CHECK 제약이 최종 방어선)
async function updateItemStock(id, { available_qty, total_qty }) {
  if (available_qty > total_qty) {
    throw new Error("대여가능 수량은 총 수량을 넘을 수 없습니다.");
  }

  const { data, error } = await supabaseClient
    .from("items")
    .update({ available_qty, total_qty })
    .eq("id", id)
    .select()
    .single();

  if (error) {
    if (error.code === "23514") {
      throw new Error("대여가능 수량은 총 수량을 넘을 수 없습니다.");
    }
    throw error;
  }
  return { ...data, categoryLabel: categoryLabelOf(data.category) };
}

// 삭제: 해당 물품에 대여 이력(loans)이 있으면 DB가 FK 제약으로 삭제를 막는다(이력 보존)
async function deleteItem(id) {
  const { error } = await supabaseClient.from("items").delete().eq("id", id);

  if (error) {
    if (error.code === "23503") {
      throw new Error("대여 이력이 있는 물품은 삭제할 수 없습니다.");
    }
    throw error;
  }
}

window.LabBotItems = {
  searchItems,
  fetchItemById,
  fetchLocations,
  createItem,
  updateItemStock,
  deleteItem,
  categoryLabelOf,
  computeStockStatus,
  canRentItem,
  STOCK_STATUS_LABEL,
  STOCK_STATUS_BADGE_CLASS,
};
