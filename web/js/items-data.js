// LabBot - 물품 데이터 (Supabase items 테이블 연동)
// 등록/검색/재고수정/삭제 규칙은 web/docs/labbot_schema.sql의 items 테이블 + 제약조건이 최종 근거.

// 생명공학 실험실 물품 유형 — items.item_type/category 값과 그대로 맞춘다
// (예전엔 광학/분리/측정기기로 나눴었는데, 실제 물품 데이터를 생명공학 실험실
// 기준으로 바꾸면서 장비/시약/소모품/PPE/안전물품 5종으로 단순화했다)
// 로봇(Webots) 체크포인트와 그대로 이어지는 고정 위치 9곳.
// 자유 입력을 허용하면 "기기실-1"/"기기실1"/"기기실 1"처럼 오타로 서로 다른 위치가
// 되어버려서 로봇 체크포인트가 어긋난다 — 그래서 등록 화면은 이 목록만 고르게 한다.
const LAB_LOCATIONS = [
  "일반실험실",
  "기기실-1",
  "기기실-2",
  "세포배양실",
  "시약보관실",
  "냉장보관실",
  "냉동보관실",
  "소모품보관실",
  "안전장비함",
];

const LAB_CATEGORIES = [
  { key: "all", label: "전체" },
  { key: "EQUIPMENT", label: "장비" },
  { key: "REAGENT", label: "시약" },
  { key: "CONSUMABLE", label: "소모품" },
  { key: "PPE", label: "PPE" },
  { key: "SAFETY", label: "안전물품" },
];

// 실제 물품 사진을 등록/관리하는 기능이 없어서(사진 업로드·저장 부담) 대신 분류별로
// 자동으로 붙는 아이콘을 물품마다 보여준다 — 물품을 새로 등록해도 사람이 사진을 따로
// 올릴 필요 없이 category만 고르면 바로 적용된다. 로고 아이콘과 같은 라인 스타일로 통일.
const CATEGORY_ICON = {
  EQUIPMENT: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>`,
  REAGENT: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2h6"/><path d="M10 2v6.3L5.2 17a3 3 0 0 0 2.6 4.5h8.4a3 3 0 0 0 2.6-4.5L14 8.3V2"/><path d="M7 15h10"/></svg>`,
  CONSUMABLE: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="12" rx="1.5"/><path d="M4 8l3.5-4.5h9L20 8"/><path d="M9.5 12.5h5"/></svg>`,
  PPE: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z"/></svg>`,
  SAFETY: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 20h20L12 2z"/><path d="M12 9v5"/><path d="M12 17h.01"/></svg>`,
};
const DEFAULT_CATEGORY_ICON = CATEGORY_ICON.EQUIPMENT;

function categoryIconOf(key) {
  return CATEGORY_ICON[key] || DEFAULT_CATEGORY_ICON;
}

// ---------- 재고 상태 계산 (공통 함수 — 여러 파일에 흩어놓지 않고 여기 한 곳에만 둔다) ----------
//
// manual_status: DB에 저장되는 "관리자가 직접 정하는" 값. 지금은 null 또는 'MAINTENANCE'만 쓴다.
// 나머지 상태(OUT_OF_STOCK/LOW_STOCK/EXPIRED/EXPIRING_SOON/AVAILABLE)는 저장하지 않고
// available_qty/minimum_qty/expires_at을 기준으로 매번 새로 계산한다 — DB 값을 그대로
// 믿으면 날짜가 지나도 상태가 안 바뀌는 문제가 생기기 때문이다.
const STOCK_STATUS_LABEL = {
  AVAILABLE: "대여 가능",
  FIXED_ASSET: "고정 설비",
  LOW_STOCK: "재고 부족",
  OUT_OF_STOCK: "품절",
  EXPIRING_SOON: "유효기간 임박",
  EXPIRED: "유효기간 만료",
  MAINTENANCE: "점검 중",
};

const STOCK_STATUS_BADGE_CLASS = {
  AVAILABLE: "badge-available",
  FIXED_ASSET: "badge-inuse",
  LOW_STOCK: "badge-sev-medium",
  OUT_OF_STOCK: "badge-sev-high",
  EXPIRING_SOON: "badge-sev-medium",
  EXPIRED: "badge-sev-high",
  MAINTENANCE: "badge-inuse",
};

// 이 상태들은 재고/유효기간 문제가 있어도 "경고만" — 대여 자체는 막지 않는다.
// MAINTENANCE / EXPIRED / OUT_OF_STOCK만 실제로 대여를 막는다.
const NON_RENTABLE_STATUSES = new Set(["MAINTENANCE", "EXPIRED", "OUT_OF_STOCK"]);

// 우선순위: MAINTENANCE > EXPIRED > OUT_OF_STOCK > EXPIRING_SOON > LOW_STOCK > AVAILABLE
// (재고가 0개인데 유효기간 임박이 먼저 뜨면 "품절"인 걸 놓치고 헷갈리기 쉬워서, 품절을
// 유효기간 임박보다 먼저 확인한다.)
function computeStockStatus(item) {
  if (item.manual_status === "MAINTENANCE") {
    return "MAINTENANCE";
  }

  if (item.is_rentable === false) {
    return "FIXED_ASSET";
  }

  let expirationDate = null;
  if (item.expires_at) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    expirationDate = new Date(`${item.expires_at}T00:00:00`);
    if (expirationDate < today) {
      return "EXPIRED";
    }
  }

  if (item.available_qty === 0) {
    return "OUT_OF_STOCK";
  }

  if (expirationDate) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const thirtyDaysLater = new Date(today);
    thirtyDaysLater.setDate(thirtyDaysLater.getDate() + 30);
    if (expirationDate <= thirtyDaysLater) {
      return "EXPIRING_SOON";
    }
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

// LOW_STOCK/EXPIRING_SOON은 "경고만" — 실제로 대여는 계속 가능하다는 걸 라벨에서도 분명히 한다.
const STOCK_STATUS_FULL_LABEL = {
  ...STOCK_STATUS_LABEL,
  LOW_STOCK: "재고 부족 · 대여 가능",
  EXPIRING_SOON: "유효기간 임박 · 대여 가능",
};

// DB에서 온 문자열을 innerHTML에 그대로 꽂지 않기 위한 공용 이스케이프 함수.
// (물품명/위치/사용자 이름/메모 등 — 저장형 XSS 방지)
function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// 대여 가능 여부도 여기서만 판단한다 — items.js 등 다른 파일이 각자 다시 계산하지 않는다.
function canRentItem(item) {
  return item.is_rentable !== false && !NON_RENTABLE_STATUSES.has(computeStockStatus(item));
}

function categoryLabelOf(key) {
  const found = LAB_CATEGORIES.find((c) => c.key === key);
  return found ? found.label : key;
}

// qr_code는 더 이상 items 테이블에 없다(별도 item_qr_codes 테이블, 관리자만 조회 가능 —
// docs/labbot_schema.sql 24번 섹션). item_qr_codes(qr_code)를 함께 embed해서 요청하면
// 관리자에게는 값이 채워지고, 일반 사용자에게는 RLS가 막아서 null로 온다(에러 아님) —
// 아래 헬퍼가 그 두 경우를 하나로 정리해준다.
const ITEMS_SELECT = "*, item_qr_codes(qr_code)";

function qrCodeOf(item) {
  const rel = item && item.item_qr_codes;
  if (!rel) return null;
  const row = Array.isArray(rel) ? rel[0] : rel;
  return (row && row.qr_code) || null;
}

// 검색: 이름 부분일치 + category/location 필터를 동시에(AND) 적용
async function searchItems({ name = "", category = "all", location = "all" } = {}) {
  let query = supabaseClient.from("items").select(ITEMS_SELECT).order("name", { ascending: true });

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
  const { data, error } = await supabaseClient.from("items").select(ITEMS_SELECT).eq("id", id).single();
  if (error) throw error;
  return { ...data, categoryLabel: categoryLabelOf(data.category) };
}

// 검색/필터용 위치 목록 (현재 등록된 물품 기준 중복제거)
async function fetchLocations() {
  const { data, error } = await supabaseClient.from("items").select("location");
  if (error) throw error;
  return [...new Set(data.map((row) => row.location))].sort();
}

async function fetchStorageFixtures() {
  const { data, error } = await supabaseClient
    .from("items")
    .select("id,name")
    .eq("is_rentable", false)
    .order("name", { ascending: true });
  if (error) throw error;
  return data || [];
}

// 등록: qr_code는 DB 트리거가 서버에서 랜덤 발급, available_qty는 total_qty로 시작
// item_type은 category와 같은 값을 쓴다(생명공학 물품 확장 이후로 두 컬럼을 통일했다).
async function createItem({
  name,
  category,
  location,
  total_qty,
  unit = null,
  minimum_qty = null,
  storage_condition = null,
  expires_at = null,
  notes = "",
}) {
  const { data, error } = await supabaseClient
    .from("items")
    .insert({
      name,
      category,
      location,
      total_qty,
      available_qty: total_qty,
      item_type: category,
      unit,
      minimum_qty,
      storage_condition,
      expires_at,
      notes,
    })
    .select()
    .single();

  if (error) throw error;
  return { ...data, categoryLabel: categoryLabelOf(data.category) };
}

// 관리자가 등록 이후에 고칠 수 있는 필드들(재고 수량 제외 — 그건 updateItemStock이 담당).
async function updateItemDetails(id, { minimum_qty, storage_condition, expires_at, notes, manual_status }) {
  const { data, error } = await supabaseClient
    .from("items")
    .update({ minimum_qty, storage_condition, expires_at, notes, manual_status })
    .eq("id", id)
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
  LAB_LOCATIONS,
  searchItems,
  fetchItemById,
  fetchLocations,
  fetchStorageFixtures,
  createItem,
  updateItemStock,
  updateItemDetails,
  deleteItem,
  categoryLabelOf,
  categoryIconOf,
  qrCodeOf,
  computeStockStatus,
  canRentItem,
  escapeHtml,
  STOCK_STATUS_LABEL,
  STOCK_STATUS_FULL_LABEL,
  STOCK_STATUS_BADGE_CLASS,
};
