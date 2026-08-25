// LabBot - 파손 신고 (Supabase damage_reports 테이블 + damage-photos 스토리지 + gemini-damage-assess 연동)
// 흐름: 사진 업로드 -> damage_reports insert(status='pending') -> gemini-damage-assess 함수 호출
//       -> 함수가 사진을 제미나이 비전으로 분석해서 severity/ai_result/status를 갱신.
// 마이페이지(신고 접수), 관리자 화면(목록 조회) 양쪽에서 공통으로 사용 (window.LabBotDamage 제공)

const DAMAGE_REPORT_SELECT = "*, items(name, category), profiles(name)";

const DAMAGE_SEVERITY_LABEL = {
  경미: "경미",
  보통: "보통",
  심각: "심각",
  즉시교체: "즉시교체",
};

// safety-events용 badge-sev-*를 그대로 재사용하고, "즉시교체"만 한 단계 더 강한 badge-sev-critical.
const DAMAGE_SEVERITY_BADGE_CLASS = {
  경미: "badge-sev-low",
  보통: "badge-sev-medium",
  심각: "badge-sev-high",
  즉시교체: "badge-sev-critical",
};

const DAMAGE_STATUS_LABEL = {
  pending: "AI 분석 중",
  analyzed: "분석 완료",
  failed: "분석 실패",
};

// 사진을 damage-photos 버킷에 올리고 공개 URL을 돌려준다.
// 파일명에 타임스탬프+랜덤을 섞어서 같은 이름을 두 번 올려도 서로 덮어쓰지 않게 한다.
async function uploadDamagePhoto(file, session) {
  const ext = (file.name.split(".").pop() || "jpg").toLowerCase();
  const path = `${session.id}/${Date.now()}_${Math.random().toString(36).slice(2, 8)}.${ext}`;

  const { error: uploadError } = await supabaseClient.storage.from("damage-photos").upload(path, file, {
    contentType: file.type || "image/jpeg",
    upsert: false,
  });
  if (uploadError) throw uploadError;

  const { data } = supabaseClient.storage.from("damage-photos").getPublicUrl(path);
  return data.publicUrl;
}

// 파손 신고 접수: 사진 업로드 -> damage_reports insert -> gemini-damage-assess 호출까지 한 번에.
// AI 분석(gemini-damage-assess)이 실패해도 신고 자체(행)는 이미 저장돼 있으니 관리자가 나중에
// 사진을 직접 보고 판단할 수 있다 — 그래서 이 함수는 분석 실패를 던지지 않고 assessment.error로 알려준다.
async function submitDamageReport({ item, session, file, note }) {
  if (!file) throw new Error("파손 사진을 첨부해주세요.");

  const photo_url = await uploadDamagePhoto(file, session);

  const { data: report, error: insertError } = await supabaseClient
    .from("damage_reports")
    .insert({
      item_id: item.id,
      reported_by: session.id,
      note: note || "",
      photo_url,
      status: "pending",
    })
    .select(DAMAGE_REPORT_SELECT)
    .single();

  if (insertError) throw insertError;

  let assessment = null;
  try {
    const { data, error } = await supabaseClient.functions.invoke("gemini-damage-assess", {
      body: { report_id: report.id },
    });
    if (error) throw error;
    assessment = data;
  } catch (err) {
    console.error("LabBot: 파손 사진 AI 분석 실패", err);
    assessment = { error: err.message || "AI 분석에 실패했습니다. 관리자가 사진을 직접 확인할 예정입니다." };
  }

  return { report, assessment };
}

// 관리자용: 전체 파손 신고 목록 (최신순)
async function fetchAllDamageReports() {
  const { data, error } = await supabaseClient
    .from("damage_reports")
    .select(DAMAGE_REPORT_SELECT)
    .order("created_at", { ascending: false });

  if (error) throw error;
  return data;
}

window.LabBotDamage = {
  DAMAGE_SEVERITY_LABEL,
  DAMAGE_SEVERITY_BADGE_CLASS,
  DAMAGE_STATUS_LABEL,
  submitDamageReport,
  fetchAllDamageReports,
};
