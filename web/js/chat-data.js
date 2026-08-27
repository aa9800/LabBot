// LabBot - 챗봇 대화 이력 (Supabase chat_messages 테이블 연동)
// 새로고침하면 대화가 사라지는 문제(GPT 리뷰 지적)를 고치려고, 로그인한 사용자의
// user/bot 메시지를 각각 한 행씩 남긴다. 비로그인 사용자는 저장 대상이 아니라서
// 두 함수 모두 session이 없으면 조용히 아무 것도 하지 않는다(호출부에서 매번 if
// 감싸지 않아도 되게).
// docs/labbot_schema.sql 18번 섹션 참고.

async function fetchChatHistory(session) {
  if (!session) return [];
  const { data, error } = await supabaseClient
    .from("chat_messages")
    .select("*")
    .eq("user_id", session.id)
    .order("created_at", { ascending: true });

  if (error) {
    console.warn("LabBot: 챗봇 대화 이력을 못 가져왔습니다", error);
    return [];
  }
  return data;
}

async function saveChatMessage(session, { role, content, recommended_item_ids = [] }) {
  if (!session) return;
  const { error } = await supabaseClient.from("chat_messages").insert({
    user_id: session.id,
    role,
    content,
    recommended_item_ids,
  });
  // 저장 실패해도 화면상 대화 자체는 이미 표시됐으니 조용히 경고만 남기고 넘어간다 —
  // 이력 저장은 편의 기능이지 대화 자체의 성공 조건이 아니다.
  if (error) console.warn("LabBot: 챗봇 메시지 저장 실패", error);
}

// 로그아웃 시 호출 — 사용자 요청("로그아웃하면 대화기록이 초기화")으로 추가.
// 로그인 상태로 있는 동안은(페이지를 옮겨도) chat_messages에 계속 쌓여서 이어지지만,
// 로그아웃하는 순간 그 계정의 기록을 서버에서 완전히 지운다 — 다음에 같은 계정으로
// 다시 로그인해도 처음부터 새로 시작한다. signOut() 이전에 호출해야 한다 — 로그아웃한
// 뒤에는 auth.uid()가 없어져서 RLS(chat_messages_own)가 삭제 자체를 막는다.
async function clearChatHistory(session) {
  if (!session) return;
  const { error } = await supabaseClient.from("chat_messages").delete().eq("user_id", session.id);
  if (error) console.warn("LabBot: 로그아웃 시 대화기록 초기화 실패", error);
}

window.LabBotChat = {
  fetchChatHistory,
  saveChatMessage,
  clearChatHistory,
};
