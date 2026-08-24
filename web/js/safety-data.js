// LabBot - 안전 이벤트(Safety) 데이터 (Supabase safety_events / action_logs 테이블 연동)
// 상태값·전이 규칙은 docs/labbot_schema.sql의 safety_events.status CHECK 제약이 최종 근거.
// 로봇(robot-sim, Webots)이 감지한 이벤트도 전부 이 테이블에 쌓인다 — 여기서는 "확인 후 조치"만 담당.

// 상태별로 "다음에 누를 수 있는 버튼" 목록. NEEDS_REVIEW는 로봇/AI가 자동 감지한
// 상태라서 사람이 검토하기 전까지는 절대 자동으로 OPEN 이상으로 넘어가지 않는다.
const SAFETY_NEXT_ACTIONS = {
  NEEDS_REVIEW: [
    { action: "OPEN", label: "확인 → 접수(OPEN)" },
    { action: "FALSE_POSITIVE", label: "오탐(잘못 감지) 처리" },
  ],
  OPEN: [{ action: "ASSIGNED", label: "담당자 배정" }],
  ASSIGNED: [{ action: "IN_PROGRESS", label: "조치 시작" }],
  IN_PROGRESS: [{ action: "RESOLVED", label: "조치 완료" }],
  RESOLVED: [{ action: "CLOSED", label: "종결" }],
  CLOSED: [],
  FALSE_POSITIVE: [],
};

const SAFETY_STATUS_LABEL = {
  NEEDS_REVIEW: "검토 필요",
  OPEN: "접수됨",
  ASSIGNED: "담당자 배정",
  IN_PROGRESS: "조치 중",
  RESOLVED: "조치 완료",
  CLOSED: "종결",
  FALSE_POSITIVE: "오탐",
};

const SAFETY_SEVERITY_LABEL = { HIGH: "높음", MEDIUM: "보통", LOW: "낮음" };

async function fetchSafetyEvents({ status = "all", severity = "all" } = {}) {
  let query = supabaseClient
    .from("safety_events")
    .select("*")
    .order("detected_at", { ascending: false });

  if (status !== "all") query = query.eq("status", status);
  if (severity !== "all") query = query.eq("severity", severity);

  const { data, error } = await query;
  if (error) throw error;
  return data;
}

async function fetchSafetyEventDetail(id) {
  const { data: event, error: eventError } = await supabaseClient
    .from("safety_events")
    .select("*")
    .eq("id", id)
    .single();
  if (eventError) throw eventError;

  const { data: logs, error: logsError } = await supabaseClient
    .from("action_logs")
    .select("*")
    .eq("event_id", id)
    .order("created_at", { ascending: true });
  if (logsError) throw logsError;

  return { event, logs };
}

// 상태를 다음 단계로 옮기고, 그 변화를 action_logs에 감사이력으로 남긴다.
// 두 작업을 순서대로 하기 때문에 완전한 트랜잭션은 아니다 — 두 번째(로그 기록)가
// 실패하면 상태는 이미 바뀐 채로 로그만 안 남을 수 있음(발표 범위에서는 허용되는 단순화).
async function transitionSafetyEvent(id, { nextStatus, actorName, note }) {
  const patch = { status: nextStatus };
  if (nextStatus === "RESOLVED") {
    patch.resolution_note = note || "";
    patch.resolved_at = new Date().toISOString();
  }

  const { error: updateError } = await supabaseClient
    .from("safety_events")
    .update(patch)
    .eq("id", id);
  if (updateError) throw updateError;

  const { error: logError } = await supabaseClient.from("action_logs").insert({
    event_id: id,
    actor: actorName,
    action: nextStatus,
    note: note || "",
  });
  if (logError) throw logError;
}

window.LabBotSafety = {
  SAFETY_NEXT_ACTIONS,
  SAFETY_STATUS_LABEL,
  SAFETY_SEVERITY_LABEL,
  fetchSafetyEvents,
  fetchSafetyEventDetail,
  transitionSafetyEvent,
};
