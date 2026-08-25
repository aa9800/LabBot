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

const MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024; // 5MB — 휴대폰 카메라 사진 정도는 넉넉히 통과, 원본 RAW급은 차단

// 사진을 damage-photos 버킷에 올리고 "경로"만 돌려준다(공개 URL이 아님 — 버킷이
// 비공개라 URL만으로는 못 열고, 매번 서명 URL을 새로 발급해야 한다. docs/labbot_schema.sql
// 19번 섹션 참고). 파일명에 타임스탬프+랜덤을 섞어서 같은 이름을 두 번 올려도 안 덮어쓴다.
// 크기·MIME 제한은 클라이언트(여기)와 스토리지 버킷 설정(docs/labbot_schema.sql 15번 섹션)
// 양쪽에 걸어둔다 — 여기 검사는 사용자에게 바로 알려주기 위함이고, 버킷 설정이 실제 방어선이다
// (클라이언트 코드는 우회할 수 있어도 버킷 설정은 서버에서 강제되니까).
async function uploadDamagePhoto(file, session) {
  if (!file.type || !file.type.startsWith("image/")) {
    throw new Error("이미지 파일만 업로드할 수 있습니다.");
  }
  if (file.size > MAX_PHOTO_SIZE_BYTES) {
    throw new Error("사진 용량은 5MB를 넘을 수 없습니다.");
  }

  const ext = (file.name.split(".").pop() || "jpg").toLowerCase();
  const path = `${session.id}/${Date.now()}_${Math.random().toString(36).slice(2, 8)}.${ext}`;

  const { error: uploadError } = await supabaseClient.storage.from("damage-photos").upload(path, file, {
    contentType: file.type || "image/jpeg",
    upsert: false,
  });
  if (uploadError) throw uploadError;

  return path;
}

// 비공개 버킷이라 링크 하나로 계속 열람할 수 없다 — 열어볼 때마다(관리자가 "사진 보기"를
// 누를 때) 짧게 유효한 서명 URL을 새로 받아온다. RLS(damage_photos_read_own_or_admin)가
// 신고 당사자 본인 또는 관리자만 통과시킨다.
async function getDamagePhotoUrl(path) {
  const { data, error } = await supabaseClient.storage.from("damage-photos").createSignedUrl(path, 300); // 5분
  if (error) throw error;
  return data.signedUrl;
}

// 파손 신고 접수: 사진 업로드 -> damage_reports insert -> gemini-damage-assess 호출까지 한 번에.
// AI 분석(gemini-damage-assess)이 실패해도 신고 자체(행)는 이미 저장돼 있으니 관리자가 나중에
// 사진을 직접 보고 판단할 수 있다 — 그래서 이 함수는 분석 실패를 던지지 않고 assessment.error로 알려준다.
async function submitDamageReport({ item, session, file, note }) {
  if (!file) throw new Error("파손 사진을 첨부해주세요.");

  const photo_path = await uploadDamagePhoto(file, session);

  const { data: report, error: insertError } = await supabaseClient
    .from("damage_reports")
    .insert({
      item_id: item.id,
      reported_by: session.id,
      note: note || "",
      photo_path,
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
  getDamagePhotoUrl,
};
