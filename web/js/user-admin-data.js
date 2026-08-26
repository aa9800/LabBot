// LabBot - 관리자용 사용자 관리 (전체 사용자 목록 + 경고 기록)
// docs/labbot_schema.sql 31번 섹션 참고.
//
// 이메일은 profiles 테이블에 없다(auth.users 전용이라 회원가입 트리거가 name/role만
// 복사해서 넣어둔다) — 그래서 목록은 admin_list_users() RPC로만 가져올 수 있고,
// 이 RPC 자체가 관리자가 아니면 예외를 던지므로 일반 사용자는 애초에 호출해도 실패한다.

const WARNING_REASONS = ["미반납 지연", "물품 파손", "부적절한 사용", "기타"];

async function fetchAllUsers() {
  const { data, error } = await supabaseClient.rpc("admin_list_users");
  if (error) throw error;
  return data;
}

// 사용자 한 명의 경고 이력(누가 언제 왜 남겼는지) — 상세 모달에서만 쓴다.
async function fetchUserWarnings(userId) {
  const { data, error } = await supabaseClient
    .from("user_warnings")
    .select("*, creator:profiles!created_by(name)")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) throw error;
  return data;
}

// 목록 화면에서 사용자마다 경고 개수를 따로따로 조회하지 않고, 전체를 한 번에 받아서
// user_id 기준으로 직접 센다(경고 테이블 자체가 작아서 이렇게 해도 충분히 빠르다).
async function fetchWarningCounts() {
  const { data, error } = await supabaseClient.from("user_warnings").select("user_id");
  if (error) throw error;
  const counts = {};
  data.forEach((w) => {
    counts[w.user_id] = (counts[w.user_id] || 0) + 1;
  });
  return counts;
}

async function addUserWarning(userId, { reason, note, createdBy }) {
  const { data, error } = await supabaseClient
    .from("user_warnings")
    .insert({ user_id: userId, reason, note: note || "", created_by: createdBy })
    .select()
    .single();
  if (error) throw error;
  return data;
}

async function deleteUserWarning(id) {
  const { error } = await supabaseClient.from("user_warnings").delete().eq("id", id);
  if (error) throw error;
}

window.LabBotUserAdmin = {
  WARNING_REASONS,
  fetchAllUsers,
  fetchUserWarnings,
  fetchWarningCounts,
  addUserWarning,
  deleteUserWarning,
};
