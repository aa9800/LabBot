// LabBot - Robot Console 데이터 (원격조작 명령 + 카메라 스냅샷)
// robot_commands 테이블(항상 id=1 한 행)을 로봇(Webots/Raspbot)과 공유한다.
// 로봇 쪽은 robot-sim/notify_supabase.py가 이 테이블을 secret key로 읽고 쓴다.
// 카메라는 실시간 영상이 아니라, 로봇이 몇 초에 한 번씩 올리는 스냅샷을 새로 불러오는 방식이다.

// robot-camera 버킷이 비공개로 바뀌면서(docs/labbot_schema.sql 19번 섹션) 고정 공개 URL을
// 못 쓴다 — 매번 짧게 유효한 서명 URL을 새로 발급받는다. RLS(robot_camera_read_admin)가
// 관리자만 통과시키므로, 이 함수도 관리자 화면(admin.js)에서만 호출된다.
async function cameraSnapshotUrl() {
  const { data, error } = await supabaseClient.storage.from("robot-camera").createSignedUrl("latest.jpg", 30);
  if (error) throw error;
  return data.signedUrl;
}

async function fetchRobotCommand() {
  const { data, error } = await supabaseClient
    .from("robot_commands")
    .select("mode, speed, turn, updated_at")
    .eq("id", 1)
    .single();
  if (error) throw error;
  return data;
}

// mode: "auto" | "manual". manual일 때만 speed/turn이 실제로 로봇을 움직인다.
async function setRobotCommand({ mode, speed = 0, turn = 0 }) {
  const { error } = await supabaseClient
    .from("robot_commands")
    .update({ mode, speed, turn, updated_at: new Date().toISOString() })
    .eq("id", 1);
  if (error) throw error;
}

window.LabBotRobotConsole = {
  cameraSnapshotUrl,
  fetchRobotCommand,
  setRobotCommand,
};
