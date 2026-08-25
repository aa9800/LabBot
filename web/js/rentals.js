// LabBot - 대여/반납 (Supabase loans 테이블 연동)
// 재고 증감(available_qty -1/+1)은 DB 트리거가 처리한다 (docs/labbot_schema.sql 8번 섹션 참고).
// 마이페이지, 물품목록, 관리자 화면에서 공통으로 사용 (window.LabBotRentals 제공)

const LOAN_SELECT = "*, items(id, name, category, location)";

// 연체 여부: 저장하지 않고 조회할 때마다 계산하는 파생값
function isOverdue(loan) {
  return !loan.returned_at && new Date() > new Date(loan.due_at);
}

// 대여: available_qty > 0인 물품만 대여 가능. due_at은 서버가 오늘+7일로 기본 발급.
async function createLoan(item, session, source = "manual") {
  if (item.available_qty <= 0) {
    throw new Error("대여 가능한 재고가 없습니다.");
  }

  const { data, error } = await supabaseClient
    .from("loans")
    .insert({ user_id: session.id, item_id: item.id, source })
    .select(LOAN_SELECT)
    .single();

  if (error) {
    if (error.code === "23514") {
      throw new Error("대여 가능한 재고가 없습니다.");
    }
    throw error;
  }
  return data;
}

// 사용(소모): 소모품/시약처럼 "빌렸다가 돌려주는" 개념이 없는 물품용.
// loans 행을 만들면서 바로 반납완료 상태로 넣는다 — INSERT 트리거(재고 -1)만 발동하고
// UPDATE 트리거(재고 +1)는 발동할 일이 없어서(이미 반납완료 상태로 들어감), 재고가
// 영구적으로 줄어든다. 그래도 이력은 loans에 그대로 남아 대여 이력 화면에서 보인다.
async function consumeItem(item, session, source = "manual") {
  if (item.available_qty <= 0) {
    throw new Error("남은 재고가 없습니다.");
  }

  const now = new Date().toISOString();
  const { data, error } = await supabaseClient
    .from("loans")
    .insert({
      user_id: session.id,
      item_id: item.id,
      source,
      status: "반납완료",
      borrowed_at: now,
      returned_at: now,
    })
    .select(LOAN_SELECT)
    .single();

  if (error) {
    if (error.code === "23514") {
      throw new Error("남은 재고가 없습니다.");
    }
    throw error;
  }
  return data;
}

// item_type 기준으로 "대여"(반납 필요) vs "사용"(소모, 반납 없음)을 구분한다.
// 장비/PPE/안전물품은 대여, 시약/소모품은 사용 — 여러 파일에서 각자 판단하지 않게 여기 한 곳에 둔다.
function isConsumable(item) {
  return item.item_type === "REAGENT" || item.item_type === "CONSUMABLE";
}

// 반납: 대여중 상태의 loans 행만 반납완료로 전환
async function returnLoan(loanId) {
  const { data, error } = await supabaseClient
    .from("loans")
    .update({ returned_at: new Date().toISOString(), status: "반납완료" })
    .eq("id", loanId)
    .eq("status", "대여중")
    .select(LOAN_SELECT)
    .single();

  if (error) {
    if (error.code === "PGRST116") {
      throw new Error("이미 반납된 대여입니다.");
    }
    throw error;
  }
  return data;
}

// 내 대여 목록: 로그인한 사용자 본인 것만
async function fetchMyLoans(userId) {
  const { data, error } = await supabaseClient
    .from("loans")
    .select(LOAN_SELECT)
    .eq("user_id", userId)
    .order("borrowed_at", { ascending: false });

  if (error) throw error;
  return data;
}

// 관리자용: 전체 대여/반납 이력
async function fetchAllLoans() {
  const { data, error } = await supabaseClient
    .from("loans")
    .select("*, items(id, name, category, location), profiles(name)")
    .order("borrowed_at", { ascending: false });

  if (error) throw error;
  return data;
}

window.LabBotRentals = {
  createLoan,
  consumeItem,
  isConsumable,
  returnLoan,
  fetchMyLoans,
  fetchAllLoans,
  isOverdue,
};
