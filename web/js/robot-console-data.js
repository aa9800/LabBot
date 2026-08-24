// LabBot - Robot Console 데이터 (원격조작 명령 + 카메라 스냅샷)
// robot_commands 테이블(항상 id=1 한 행)을 로봇(Webots/Raspbot)과 공유한다.
// 로봇 쪽은 robot-sim/notify_supabase.py가 이 테이블을 secret key로 읽고 쓴다.
// 카메라는 실시간 영상이 아니라, 로봇이 몇 초에 한 번씩 올리는 스냅샷을 새로 불러오는 방식이다.

function cameraSnapshotUrl() {
  const base = window.LABBOT_SUPABASE_CONFIG.url;
  // 캐시 방지용으로 매번 다른 쿼리스트링을 붙인다 — 안 붙이면 브라우저가 옛 사진을 계속 보여준다.
  return `${base}/storage/v1/object/public/robot-camera/latest.jpg?t=${Date.now()}`;
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
