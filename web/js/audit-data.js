// LabBot - 재고실사(Audit) 데이터 (Supabase audit_sessions / audit_mismatches 연동)
// 확인 목록 제출 -> 세션 생성 + 미확인 물품 자동 기록은 DB 함수(run_inventory_audit)가
// 하나의 트랜잭션으로 처리한다(docs/labbot_schema.sql 9번 섹션). 사람이 체크리스트로
// 만든 item_id 목록이든, 로봇이 스캔해서 만든 목록이든 이 함수 하나만 호출하면 되고
// 로직은 완전히 동일하다.

// 실사 제출: 실제로 확인한 item_id 목록만 넘기면 된다.
async function submitAudit(confirmedItemIds) {
  const { data, error } = await supabaseClient.rpc("run_inventory_audit", {
    confirmed_item_ids: confirmedItemIds,
  });
  if (error) throw error;
  return data; // 새로 생성된 audit_sessions.id
}

// 실사 세션 목록 (미확인 개수까지 함께 계산해서 반환)
async function fetchAuditSessions() {
  const { data: sessions, error } = await supabaseClient
    .from("audit_sessions")
    .select("*")
    .order("started_at", { ascending: false });
  if (error) throw error;

  const { data: mismatches, error: mismatchError } = await supabaseClient
    .from("audit_mismatches")
    .select("session_id");
  if (mismatchError) throw mismatchError;

  const countBySession = {};
  mismatches.forEach((m) => {
    countBySession[m.session_id] = (countBySession[m.session_id] || 0) + 1;
  });

  return sessions.map((s) => ({ ...s, mismatch_count: countBySession[s.id] || 0 }));
}

// 특정 실사 세션에서 미확인 처리된 물품 목록
async function fetchAuditMismatches(sessionId) {
  const { data, error } = await supabaseClient
    .from("audit_mismatches")
    .select("*, items(name, location)")
    .eq("session_id", sessionId);
  if (error) throw error;
  return data;
}

window.LabBotAudit = {
  submitAudit,
  fetchAuditSessions,
  fetchAuditMismatches,
};
