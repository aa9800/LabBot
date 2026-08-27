// LabBot - Robot Console 데이터 (원격조작 명령 + 카메라 스냅샷)
// robot_commands 테이블(항상 id=1 한 행)을 로봇(Webots/Raspbot)과 공유한다.
// 로봇 쪽은 robot-sim/notify_supabase.py가 이 테이블을 secret key로 읽고 쓴다.
// 카메라는 실시간 영상이 아니라, 로봇이 몇 초에 한 번씩 올리는 스냅샷을 새로 불러오는 방식이다.

// robot-camera 버킷이 비공개로 바뀌면서(docs/labbot_schema.sql 19번 섹션) 고정 공개 URL을
// 못 쓴다 — 짧게 유효한 서명 URL을 발급받는다. RLS(robot_camera_read_admin)가 관리자만
// 통과시키므로, 이 함수도 관리자 화면(admin.js)에서만 호출된다.
//
// 폴링 주기(1초)마다 매번 새 서명 URL을 발급받으면 Storage API 호출이 그만큼 늘어난다 —
// 서명 URL 자체는 60초 유효하게 발급받아두고, 그 안에서는 캐시된 URL을 재사용하면서
// 뒤에 타임스탬프 쿼리만 붙여 브라우저 캐시를 무력화한다(같은 URL이면 이미지가 안 바뀐
//것처럼 캐시된 그림을 계속 보여줄 수 있어서).
let _cachedSignedUrl = null;
let _cachedSignedUrlExpiresAt = 0;

async function cameraSnapshotUrl() {
  const now = Date.now();
  if (!_cachedSignedUrl || now > _cachedSignedUrlExpiresAt) {
    const { data, error } = await supabaseClient.storage.from("robot-camera").createSignedUrl("latest.jpg", 60);
    if (error) throw error;
    _cachedSignedUrl = data.signedUrl;
    _cachedSignedUrlExpiresAt = now + 55_000; // 60초 유효 중 55초까지만 재사용(여유분 5초)
  }
  const bust = _cachedSignedUrl.includes("?") ? "&" : "?";
  return `${_cachedSignedUrl}${bust}_ts=${now}`;
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

let _currentMode = localStorage.getItem("labbot_target_mode") || "real";
let _cachedLocalIp = _currentMode === "sim" ? "127.0.0.1" : "10.42.0.1";

function setTargetMode(mode) {
  _currentMode = mode === "sim" ? "sim" : "real";
  _cachedLocalIp = _currentMode === "sim" ? "127.0.0.1" : "10.42.0.1";
  localStorage.setItem("labbot_target_mode", _currentMode);
  return _currentMode;
}

function getTargetMode() {
  return _currentMode;
}

// local_ip는 현재 타겟 모드에 맞는 IP를 즉시 반환
async function fetchRobotIp() {
  return _cachedLocalIp;
}

function getDirectStreamUrl(localIp, port = 8080) {
  const ip = localIp || _cachedLocalIp;
  return `http://${ip}:${port}/stream`;
}

// 스트림 서버의 /health 엔드포인트를 빠르게 찔러보아 직결 가능 여부를 판별한다.
async function checkStreamHealth(localIp, port = 8080, timeoutMs = 1200) {
  const ip = localIp || _cachedLocalIp;
  const url = `http://${ip}:${port}/health`;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const resp = await fetch(url, { method: "GET", mode: "cors", signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) return false;
    const data = await resp.json();
    return data && data.streaming === true;
  } catch {
    return false;
  }
}

// cam_pan/cam_tilt는 fetchRobotCommand와 일부러 분리했다 — 이 두 컬럼은
// docs/labbot_schema.sql의 마이그레이션을 실행해야 생기는데, 아직 안 돌렸으면 이 조회만
// 실패하고(cam 초기값은 화면 기본값 90/90으로 대체) 모드 배지 등 나머지 폴링은 계속
// 정상 동작해야 하기 때문이다.
async function fetchCameraAngle() {
  const { data, error } = await supabaseClient
    .from("robot_commands")
    .select("cam_pan, cam_tilt")
    .eq("id", 1)
    .single();
  if (error) throw error;
  return data;
}

// mode: "auto" | "manual". manual일 때만 speed/turn이 실제로 로봇을 움직인다.
// cam_pan/cam_tilt: 0~180도 서보 각도(생략하면 기존 값 유지 — 매번 안 보내도 됨).
// 로컬 직결 스트림 IP가 있으면 0ms 초저지연으로 모터를 즉시 구동하고, Supabase에도 상태를 동기화한다.
async function setRobotCommand({ mode, speed = 0, turn = 0, cam_pan, cam_tilt }) {
  // 1. 로컬 직결 초저지연(0ms) 주행 명령 전송
  const targetIp = _cachedLocalIp || "10.42.0.1";
  if (targetIp && targetIp !== "127.0.0.1") {
    const params = new URLSearchParams({ mode, speed, turn });
    fetch(`http://${targetIp}:8080/drive?${params.toString()}`, { mode: "no-cors" }).catch(() => {});
  }

  // 2. Supabase DB 상태 동기화 (클라우드 상태 보존)
  const payload = { mode, speed, turn, updated_at: new Date().toISOString() };
  if (cam_pan !== undefined) payload.cam_pan = cam_pan;
  if (cam_tilt !== undefined) payload.cam_tilt = cam_tilt;
  try {
    await supabaseClient.from("robot_commands").update(payload).eq("id", 1);
  } catch (err) {
    console.debug("LabBot: Supabase 주행 명령 동기화 실패(로컬 직결 동작 중)", err);
  }
}

// 카메라 각도만 바꿀 때는 mode/speed/turn을 건드리지 않는다 — 주행 중에 카메라만 돌려도
// 로봇이 갑자기 멈추거나 자동/수동 모드가 바뀌면 안 되기 때문에, robot_commands의
// mode/speed/turn은 그대로 두고 cam_pan/cam_tilt만 갱신하는 별도 함수로 분리했다.
// 로컬 직결 스트림 IP가 있으면 0ms 초저지연으로 로봇에 직접 쏘고, Supabase에도 상태를 동기화한다.
async function setCameraAngle({ cam_pan, cam_tilt }) {
  // 1. 로컬 직결 초저지연(0ms) 서보 명령 전송
  const targetIp = _cachedLocalIp || "10.42.0.1";
  if (targetIp && targetIp !== "127.0.0.1") {
    const params = new URLSearchParams();
    if (cam_pan !== undefined) params.set("pan", cam_pan);
    if (cam_tilt !== undefined) params.set("tilt", cam_tilt);
    fetch(`http://${targetIp}:8080/camera?${params.toString()}`, { mode: "no-cors" }).catch(() => {});
  }

  // 2. Supabase DB 상태 동기화 (클라우드 상태 보존)
  const payload = {};
  if (cam_pan !== undefined) payload.cam_pan = cam_pan;
  if (cam_tilt !== undefined) payload.cam_tilt = cam_tilt;
  try {
    await supabaseClient.from("robot_commands").update(payload).eq("id", 1);
  } catch (err) {
    console.debug("LabBot: Supabase 카메라 각도 동기화 실패(로컬 직결 동작 중)", err);
  }
}

async function fetchTelemetry(timeoutMs = 1000) {
  const targetIp = _cachedLocalIp || "10.42.0.1";
  if (!targetIp || targetIp === "127.0.0.1") return null;
  const url = `http://${targetIp}:8080/telemetry`;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const resp = await fetch(url, { method: "GET", mode: "cors", signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

async function triggerQrScan(localIp = "10.42.0.1") {
  const targetIp = _cachedLocalIp || localIp || "10.42.0.1";
  const url = `http://${targetIp}:8080/scan_qr`;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    const resp = await fetch(url, { method: "GET", mode: "cors", signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return await resp.json();
  } catch (err) {
    return { status: "error", message: err.message || String(err) };
  }
}

window.LabBotRobotConsole = {
  cameraSnapshotUrl,
  fetchRobotCommand,
  fetchRobotIp,
  getDirectStreamUrl,
  checkStreamHealth,
  fetchCameraAngle,
  fetchTelemetry,
  triggerQrScan,
  setRobotCommand,
  setCameraAngle,
  setTargetMode,
  getTargetMode,
};

