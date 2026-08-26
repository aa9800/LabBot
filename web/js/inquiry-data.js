// LabBot - 관리자에게 문의하기 데이터 (Supabase inquiries 테이블 연동)
// docs/labbot_schema.sql 27번 섹션 참고 — RLS로 "본인 글만 쓰고 보기, 관리자는 전체"가
// DB 단에서 강제되므로, 여기서는 그냥 필요한 쿼리만 호출하면 된다.

async function submitInquiry(session, { subject, message }) {
  const { data, error } = await supabaseClient
    .from("inquiries")
    .insert({ user_id: session.id, subject, message })
    .select()
    .single();
  if (error) throw error;
  return data;
}

// 내 문의 목록 (마이페이지)
async function fetchMyInquiries(userId) {
  const { data, error } = await supabaseClient
    .from("inquiries")
    .select("*")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) throw error;
  return data;
}

// 관리자용: 전체 문의 목록
// inquiries -> profiles 참조가 user_id/replied_by 두 개라서, 그냥 profiles(name)이라고만
// 쓰면 Supabase가 "어느 쪽 관계로 조인할지" 정하지 못해 에러를 낸다("more than one
// relationship was found"). !user_id로 어느 외래키를 쓸지 명시해서 해결한다.
async function fetchAllInquiries() {
  const { data, error } = await supabaseClient
    .from("inquiries")
    .select("*, profiles!user_id(name)")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return data;
}

// 답변 등록 — status/admin_reply/replied_by/replied_at을 한 번에 원자적으로 갱신하는
// reply_inquiry() RPC를 호출한다(여러 UPDATE로 나누면 중간에 일부만 반영될 위험이 있어서).
async function replyInquiry(inquiryId, reply) {
  const { data, error } = await supabaseClient.rpc("reply_inquiry", {
    p_inquiry_id: inquiryId,
    p_reply: reply,
  });
  if (error) throw error;
  return data;
}

// 문의 종결 — close_inquiry() RPC 호출(docs/labbot_schema.sql 28번 섹션)
async function closeInquiry(inquiryId) {
  const { data, error } = await supabaseClient.rpc("close_inquiry", {
    p_inquiry_id: inquiryId,
  });
  if (error) throw error;
  return data;
}

const INQUIRY_STATUS_LABEL = { open: "답변대기", answered: "답변완료", closed: "종결" };
// open은 관리자 조치가 필요한 상태라서, safety_events의 "조치 필요" 배지와 같은
// 강조색(badge-st-needs_review)을 쓴다 — 중립 회색(badge-pending)은 정작 처리해야
// 할 상태를 눈에 안 띄게 만들어서 요약 카드의 경고색(summary-card-warn)과도 어긋났다.
const INQUIRY_STATUS_BADGE_CLASS = { open: "badge-st-needs_review", answered: "badge-st-resolved", closed: "badge-st-closed" };

window.LabBotInquiry = {
  submitInquiry,
  fetchMyInquiries,
  fetchAllInquiries,
  replyInquiry,
  closeInquiry,
  INQUIRY_STATUS_LABEL,
  INQUIRY_STATUS_BADGE_CLASS,
};
