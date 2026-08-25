// LabBot - 대여/반납 (Supabase loans 테이블 연동)
// 재고 증감(available_qty -1/+1)은 DB 트리거가 처리한다 (docs/labbot_schema.sql 8번 섹션 참고).
// 마이페이지, 물품목록, 관리자 화면에서 공통으로 사용 (window.LabBotRentals 제공)
//
// 대여는 "예약 → 로봇 안내 → QR 확인" 2단계로 나뉜다(docs/labbot_schema.sql 20번 섹션).
// items.html/챗봇에서 누르는 건 예약(reserveItem)일 뿐이고, 실제로 물품을 받아갔다는 건
// 마이페이지에서 로봇 안내를 보고 QR을 스캔해야만(confirmPickup) 확정된다 — 그래야 "대여
// 버튼 = 즉시 대여 완료"가 아니라 로봇이 실제로 확인한 뒤에만 대여가 되는 구조가 된다.
// 반납도 마찬가지로 QR 재확인(confirmReturn) 없이는 처리되지 않는다.

const LOAN_SELECT = "*, items(id, name, category, location, qr_code, item_type, available_qty, total_qty, unit)";

// 연체 여부: 대여중 상태(실제로 픽업 확정된 것)에만 의미가 있다 — 예약중인데 due_at이
// 아직 없을(null) 수도 있어서, 그 경우는 연체가 아니라고 본다.
function isOverdue(loan) {
  return !loan.returned_at && !!loan.due_at && new Date() > new Date(loan.due_at);
}

// 예약: available_qty > 0인 물품만 예약 가능. 재고는 이 시점에 -1(기존 트리거 그대로),
// due_at은 아직 실제로 받아간 게 아니라서 NULL로 둔다 — confirmPickup()이 진짜 수령
// 시점 기준으로 7일 후를 새로 매긴다.
async function reserveItem(item, session, source = "manual") {
  if (item.available_qty <= 0) {
    throw new Error("대여 가능한 재고가 없습니다.");
  }

  const { data, error } = await supabaseClient
    .from("loans")
    .insert({ user_id: session.id, item_id: item.id, source, status: "예약중", due_at: null })
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

// 픽업 확인: 마이페이지의 로봇 안내 화면에서 QR을 스캔하면 호출한다. QR이 그 물품 것이
// 맞는지는 DB(confirm_loan_pickup RPC)에서 한 번 더 검증하므로, 여기서 클라이언트가
// 미리 비교하는 것과 별개로 서버 쪽이 최종 방어선이다.
async function confirmPickup(loanId, qrCode) {
  const { data, error } = await supabaseClient.rpc("confirm_loan_pickup", {
    p_loan_id: loanId,
    p_qr_code: qrCode,
  });
  if (error) throw error;
  return data;
}

// 반납 확인: QR을 다시 스캔해야만 반납 처리된다(confirm_loan_return RPC).
async function confirmReturn(loanId, qrCode) {
  const { data, error } = await supabaseClient.rpc("confirm_loan_return", {
    p_loan_id: loanId,
    p_qr_code: qrCode,
  });
  if (error) throw error;
  return data;
}

// 소모품 사용 확인: 장비 대여와 마찬가지로 예약만으로는 끝나지 않는다 — 마이페이지에서
// 수량을 입력하고 QR을 스캔해야만(confirm_item_usage RPC) 실제 사용으로 확정된다.
// 예약 시점에 공용 트리거가 이미 1개를 차감해뒀으므로, RPC가 실제 수량과의 차이만
// 추가로 반영한다(docs/labbot_schema.sql 21번 섹션).
async function confirmUsage(loanId, qrCode, qty) {
  const { data, error } = await supabaseClient.rpc("confirm_item_usage", {
    p_loan_id: loanId,
    p_qr_code: qrCode,
    p_qty: qty,
  });
  if (error) throw error;
  return data;
}

// 사용(소모, QR 확인 없이 바로 처리) — 지금 화면에서는 안 쓴다. 소모품도 이제
// reserveItem() → (마이페이지에서 수량 입력 + QR 스캔) → confirmUsage() 순서를 거친다.
// 이 함수는 남겨두되(예: 관리자용 즉시 사용 처리 등을 나중에 붙일 자리) UI에서 직접
// 호출하지는 않는다.
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

// 반납(QR 확인 없이 바로 처리) — 지금 화면에서는 안 쓴다. 반납은 confirmReturn()을 거쳐야
// 하지만, DB 함수 하나만으로 못 끝내는 관리자용 강제반납 등을 나중에 붙일 자리로 남겨둔다.
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
  reserveItem,
  confirmPickup,
  confirmReturn,
  confirmUsage,
  consumeItem,
  isConsumable,
  returnLoan,
  fetchMyLoans,
  fetchAllLoans,
  isOverdue,
};
