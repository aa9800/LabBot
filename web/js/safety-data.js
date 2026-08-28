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
  // ASSIGNED(담당자 배정) 단계는 뺐다 — 담당자를 실제로 지정하는 기능 없이 상태만
  // 바뀌는 건 의미가 없고, 지금 팀 규모(관리자 1~2명)에서는 굳이 필요하지도 않다.
  // 나중에 담당자를 실제로 고르는 화면을 만들면 그때 다시 넣으면 된다.
  OPEN: [{ action: "IN_PROGRESS", label: "조치 시작" }],
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

const SAFETY_RULE_LABEL = {
  PATH_OBSTRUCTION: "통로 장애물",
  FIRE_SAFETY_BLOCK: "소화기 접근 방해",
  CHEMICAL_UNATTENDED: "시약 장기 방치 의심",
  CHECKOUT_ITEM_MISMATCH: "대여 물품 불일치",
  INTRUDER_DETECTED: "비인가 인원 감지",
  "SR-01": "전방 장애물",
  "SR-03": "순찰 중 사람 감지",
  BIOHAZARD_CHECK: "정상 시설 확인(과거 기록)",
};

const EVIDENCE_NOTE_PATTERN = /\[현장증거사진:\s*([^\]\r\n]+)\]/;
const NON_ACTIONABLE_RULES = new Set(["BIOHAZARD_CHECK"]);

function getSafetyRuleLabel(ruleId) {
  return SAFETY_RULE_LABEL[ruleId] || ruleId || "알 수 없는 감지";
}

function isActionableSafetyEvent(event) {
  return Boolean(event) && !NON_ACTIONABLE_RULES.has(event.rule_id);
}

function extractSafetyEvidencePath(event) {
  const explicitPath = event && event.photo_path;
  const noteMatch = String((event && event.note) || "").match(EVIDENCE_NOTE_PATTERN);
  const path = String(explicitPath || (noteMatch && noteMatch[1]) || "").trim().replace(/^\/+/, "");
  return path && !path.includes("..") ? path : null;
}

function cleanSafetyNote(note) {
  return String(note || "").replace(EVIDENCE_NOTE_PATTERN, "").trim();
}

async function getSafetyEvidenceUrl(event, expiresInSec = 300) {
  const path = extractSafetyEvidencePath(event);
  if (!path) return null;

  const { data, error } = await supabaseClient.storage
    .from("robot-camera")
    .createSignedUrl(path, expiresInSec);
  if (error) throw error;
  return data && data.signedUrl ? data.signedUrl : null;
}

function extractEventZone(note) {
  const match = String(note || "").match(/구역\s*\[([^\]]+)\]/);
  return match ? match[1].trim() : "";
}

// 과거에 5초 간격으로 저장된 같은 감지는 삭제하지 않고 화면에서 한 묶음으로 보여준다.
// 상태/구역이 다르면 별개의 사건으로 유지하며, 90초 이상 떨어진 재발도 새 사건으로 본다.
function collapseRepeatedSafetyEvents(events, windowMs = 90000) {
  const groupsByKey = new Map();
  const collapsed = [];

  (events || []).forEach((event) => {
    const zone = extractEventZone(cleanSafetyNote(event.note));
    const key = [event.rule_id, event.source, event.status, event.severity, zone].join("|");
    const eventTime = new Date(event.detected_at).getTime();
    const previous = groupsByKey.get(key);
    const canMerge =
      previous &&
      Number.isFinite(eventTime) &&
      Number.isFinite(previous._oldestTime) &&
      previous._oldestTime - eventTime <= windowMs;

    if (canMerge) {
      previous.repeat_count += 1;
      previous._oldestTime = eventTime;
      previous.first_detected_at = event.detected_at;
      return;
    }

    const group = {
      ...event,
      repeat_count: 1,
      first_detected_at: event.detected_at,
      _oldestTime: eventTime,
    };
    groupsByKey.set(key, group);
    collapsed.push(group);
  });

  return collapsed.map(({ _oldestTime, ...event }) => event);
}

async function fetchSafetyEvents({ status = "all", severity = "all", limit = null } = {}) {
  let query = supabaseClient
    .from("safety_events")
    .select("*")
    .neq("rule_id", "BIOHAZARD_CHECK")
    .order("detected_at", { ascending: false });

  if (status !== "all") query = query.eq("status", status);
  if (severity !== "all") query = query.eq("severity", severity);
  if (Number.isInteger(limit) && limit > 0) query = query.limit(limit);

  const { data, error } = await query;
  if (error) throw error;
  return data || [];
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
// DB RPC(transition_safety_event, docs/labbot_schema.sql 14번 섹션) 하나로 묶어서 원자적으로
// 처리한다 — 예전엔 update문+insert문을 따로 두 번 날려서, 두 번째(로그 기록)가 실패하면
// 상태만 바뀌고 이력이 안 남는 문제가 있었다. 지금은 함수 안에서 둘 다 성공하거나 둘 다
// 롤백된다.
async function transitionSafetyEvent(id, { nextStatus, actorName, note }) {
  const { error } = await supabaseClient.rpc("transition_safety_event", {
    p_event_id: id,
    p_next_status: nextStatus,
    p_actor: actorName,
    p_note: note || "",
  });
  if (error) throw error;
}

window.LabBotSafety = {
  SAFETY_NEXT_ACTIONS,
  SAFETY_STATUS_LABEL,
  SAFETY_SEVERITY_LABEL,
  SAFETY_RULE_LABEL,
  getSafetyRuleLabel,
  isActionableSafetyEvent,
  cleanSafetyNote,
  extractSafetyEvidencePath,
  getSafetyEvidenceUrl,
  collapseRepeatedSafetyEvents,
  fetchSafetyEvents,
  fetchSafetyEventDetail,
  transitionSafetyEvent,
};
