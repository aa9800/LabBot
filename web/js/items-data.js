// LabBot - 물품 데이터 (Supabase items 테이블 연동)
// 등록/검색/재고수정/삭제 규칙은 web/docs/labbot_schema.sql의 items 테이블 + 제약조건이 최종 근거.

const LAB_CATEGORIES = [
  { key: "all", label: "전체" },
  { key: "optical", label: "광학기기" },
  { key: "separation", label: "분리기기" },
  { key: "measurement", label: "측정기기" },
  { key: "consumable", label: "소모품" },
  { key: "safety", label: "안전장비" },
];

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
};
