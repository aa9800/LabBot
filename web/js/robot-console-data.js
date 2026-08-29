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

let _currentMode = localStorage.getItem("labbot_target_mode") || "sim";
let _cachedLocalIp = null;  // 첫 fetchRobotIp()에서 채운다
let _activeDriveController = null;
let _driveCommandSequence = 0;
let _activeGuideTaskId = null;
let _lastPersistedGuideStatus = null;

// 모드별 기본 로봇 주소. 시뮬은 웹서버와 같은 PC에서 돌므로 페이지를 서빙한
// 호스트를 쓴다(휴대폰/다른 PC에서 열어도 올바른 대상을 가리키도록).
function _defaultIpForMode() {
  if (_currentMode === "sim") return window.location.hostname || "127.0.0.1";
  return "10.42.0.1";
}

async function sendDirectCommand(ip, path, params = {}, timeoutMs = 1200, externalSignal = null) {
  const query = new URLSearchParams(params);
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  if (externalSignal) externalSignal.addEventListener("abort", abortFromCaller, { once: true });
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetch(`http://${ip}:8080${path}?${query.toString()}`, {
      method: "GET",
      mode: "cors",
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`로봇 서버 HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    if (error?.name === "AbortError" && timedOut) {
      const timeoutError = new Error(`로봇 서버 응답 시간 초과 (${timeoutMs}ms)`);
      timeoutError.name = "TimeoutError";
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) externalSignal.removeEventListener("abort", abortFromCaller);
  }
}

function syncRobotState(payload) {
  // 조작 반응성을 위해 DB 기록은 로컬 명령 성공 뒤 백그라운드로 보낸다.
  // 로봇 구동 성공 여부와 클라우드 기록 성공 여부는 서로 다른 상태다.
  supabaseClient
    .from("robot_commands")
    .update(payload)
    .eq("id", 1)
    .then(({ error }) => {
      if (error) console.debug("LabBot: 로봇 상태 동기화 실패", error);
    });
}

// 조이스틱은 초당 수십 번 명령을 보낸다. 매 프레임 Supabase까지 쓰면 브라우저의
// 요청 큐와 DB 갱신이 쌓여 정작 로컬 주행 명령이 늦어진다. 로봇에는 매 명령을 즉시
// 보내되, 클라우드 상태 기록은 최신 값만 4Hz로 합쳐 저장한다.
let _pendingDriveState = null;
let _driveSyncTimer = null;
let _lastDriveSyncAt = 0;

function syncDriveStateThrottled(payload, immediate = false) {
  _pendingDriveState = payload;
  const flush = () => {
    _driveSyncTimer = null;
    if (!_pendingDriveState) return;
    const latest = _pendingDriveState;
    _pendingDriveState = null;
    _lastDriveSyncAt = Date.now();
    syncRobotState(latest);
  };

  if (immediate) {
    if (_driveSyncTimer) clearTimeout(_driveSyncTimer);
    flush();
    return;
  }
  if (_driveSyncTimer) return;
  const delay = Math.max(0, 250 - (Date.now() - _lastDriveSyncAt));
  _driveSyncTimer = setTimeout(flush, delay);
}

async function setTargetMode(mode) {
  const prevIp = _cachedLocalIp;
  // 타깃 전환 시 이전 로봇에 즉시 정지 명령 전송 (동시 주행 방지)
  if (prevIp) {
    await sendDirectCommand(prevIp, "/drive", { mode: "manual", speed: 0, turn: 0 }, 700).catch(() => null);
  }

  _currentMode = mode === "sim" ? "sim" : "real";
  localStorage.setItem("labbot_target_mode", _currentMode);
  await fetchRobotIp();
  return _currentMode;
}

function getTargetMode() {
  return _currentMode;
}

// local_ip는 현재 타겟 모드에 맞는 IP를 반환 (실물 로봇은 Supabase에 등록된 실제 로컬 IP 우선 조회)
async function fetchRobotIp() {
  if (_currentMode === "sim") {
    // Isaac Sim은 웹서버와 같은 PC에서 돈다. 127.0.0.1로 고정하면 휴대폰이나
    // 다른 PC에서 관리자 화면을 열었을 때 "그 기기의" 8080을 찾게 된다.
    // 페이지를 서빙한 호스트를 우선 쓰고, file:// 등으로 호스트가 없을 때만 루프백.
    _cachedLocalIp = window.location.hostname || "127.0.0.1";
    return _cachedLocalIp;
  }
  try {
    const { data } = await supabaseClient
      .from("robot_commands")
      .select("local_ip")
      .eq("id", 1)
      .single();
    if (data && data.local_ip && data.local_ip.trim()) {
      _cachedLocalIp = data.local_ip.trim();
      return _cachedLocalIp;
    }
  } catch {}
  return _cachedLocalIp || "10.42.0.1";
}

function getDirectStreamUrl(localIp, port = 8080) {
  const ip = localIp || _cachedLocalIp || "127.0.0.1";
  return `http://${ip}:${port}/stream`;
}

// 추론이 로봇 안(Physical AI)으로 옮겨졌다. 예전에는 PC의 8081 AI 서버를 봤지만,
// 이제 로봇이 스스로 탐지하고 박스를 그린 MJPEG를 8080/ai/stream 으로 내보낸다.
// PC가 꺼져 있어도 동작하므로 대상 IP는 일반 스트림과 같은 곳을 쓴다.
function getAiVisionStreamUrl(localIp, port = 8080) {
  const ip = localIp || _cachedLocalIp || _defaultIpForMode();
  return `http://${ip}:${port}/ai/stream`;
}

// 스트림 서버의 /health 엔드포인트를 빠르게 찔러보아 직결 가능 여부를 판별한다.
async function checkStreamHealth(localIp, port = 8080, timeoutMs = 1200) {
  const ip = localIp || _cachedLocalIp || "127.0.0.1";
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

// cam_pan/cam_tilt는 fetchRobotCommand와 분리하여 처리
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
// cam_pan/cam_tilt: 0~180도 서보 각도.
// 로컬 직결 스트림 IP(127.0.0.1 또는 10.42.0.1)로 초저지연 직접 전송하고, Supabase에도 상태를 동기화한다.
async function setRobotCommand({ mode, speed = 0, turn = 0, cam_pan, cam_tilt }) {
  const targetIp = _cachedLocalIp || _defaultIpForMode();
  const sequence = ++_driveCommandSequence;
  // 직전 요청이 느리게 남아 있으면 취소한다. 항상 가장 최근 입력, 특히 정지가 우선한다.
  if (_activeDriveController) _activeDriveController.abort();
  const driveController = new AbortController();
  _activeDriveController = driveController;
  let applied;
  try {
    applied = await sendDirectCommand(targetIp, "/drive", { mode, speed, turn }, 1200, driveController.signal);
  } finally {
    if (_activeDriveController === driveController) _activeDriveController = null;
  }

  // 취소 직전에 응답이 끝난 오래된 명령은 DB 상태를 다시 덮어쓰지 못하게 한다.
  if (sequence !== _driveCommandSequence) return applied;

  // 2. Supabase DB 상태 동기화
  const payload = { mode, speed, turn, updated_at: new Date().toISOString() };
  if (cam_pan !== undefined) payload.cam_pan = cam_pan;
  if (cam_tilt !== undefined) payload.cam_tilt = cam_tilt;
  const isStopOrModeChange = mode !== "manual" || (speed === 0 && turn === 0);
  syncDriveStateThrottled(payload, isStopOrModeChange);
  return applied;
}

// 카메라 각도 조절 함수
async function setCameraAngle({ cam_pan, cam_tilt }) {
  const targetIp = _cachedLocalIp || _defaultIpForMode();
  const params = {};
  if (cam_pan !== undefined) params.pan = cam_pan;
  if (cam_tilt !== undefined) params.tilt = cam_tilt;
  const applied = await sendDirectCommand(targetIp, "/camera", params);

  // 2. Supabase DB 상태 동기화
  const payload = {};
  if (cam_pan !== undefined) payload.cam_pan = cam_pan;
  if (cam_tilt !== undefined) payload.cam_tilt = cam_tilt;
  syncRobotState(payload);
  return applied;
}

async function fetchTelemetry(timeoutMs = 1000) {
  const targetIp = _cachedLocalIp || _defaultIpForMode();
  if (!targetIp) return null;
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

async function triggerQrScan(localIp) {
  const targetIp = _cachedLocalIp || localIp || _defaultIpForMode();
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

async function fetchNightGuardStatus(localIp) {
  const targetIp = _cachedLocalIp || localIp || _defaultIpForMode();
  return sendDirectCommand(targetIp, "/guard/status", {}, 1200);
}

async function configureNightGuard(config = {}, localIp) {
  const targetIp = _cachedLocalIp || localIp || _defaultIpForMode();
  return sendDirectCommand(targetIp, "/guard/config", config, 1600);
}

async function triggerNightGuardInvestigation(localIp) {
  const targetIp = _cachedLocalIp || localIp || _defaultIpForMode();
  return sendDirectCommand(targetIp, "/guard/trigger", { source: "admin-test", person: 0 }, 1600);
}

async function fetchVirtualBinding(itemId) {
  try {
    const { data, error } = await supabaseClient
      .from("virtual_lab_objects")
      .select("scene_object_id, room, display_mode")
      .eq("item_id", itemId)
      .eq("enabled", true)
      .limit(1)
      .maybeSingle();
    if (error) return null;
    return data;
  } catch {
    return null;
  }
}

async function startRobotGuide({ loanId, item, mode = "pickup" }) {
  const targetIp = _cachedLocalIp || _defaultIpForMode();
  const binding = item?.id ? await fetchVirtualBinding(item.id) : null;
  const result = await sendDirectCommand(targetIp, "/guide/start", {
    loan_id: loanId,
    item_id: item?.id || "",
    item_name: item?.name || "",
    location: item?.location || "",
    category: item?.item_type || item?.category || "",
    scene_object_id: binding?.scene_object_id || "",
    mode,
  }, 3000);

  // 안내 명령 자체는 로컬 직결로 지연 없이 보내고, 작업 이력은 Supabase에 남긴다.
  try {
    const { data, error } = await supabaseClient.from("robot_guide_tasks").insert({
      loan_id: loanId,
      item_id: item.id,
      scene_object_id: binding?.scene_object_id || result.scene_object_id || null,
      task_type: mode,
      status: result.status === "arrived" ? "arrived" : "navigating",
      shelf_code: result.shelf_code || null,
      target_x: result.target_x ?? null,
      target_y: result.target_y ?? null,
      updated_at: new Date().toISOString(),
    }).select("id").single();
    if (!error && data) _activeGuideTaskId = data.id;
  } catch (error) {
    console.debug("LabBot: 안내 작업 이력 저장 생략", error);
  }
  _lastPersistedGuideStatus = result.status;
  return result;
}

async function fetchRobotGuideStatus() {
  const targetIp = _cachedLocalIp || _defaultIpForMode();
  const result = await sendDirectCommand(targetIp, "/guide/status", {}, 1200);
  if (_activeGuideTaskId && result.status && result.status !== _lastPersistedGuideStatus) {
    _lastPersistedGuideStatus = result.status;
    supabaseClient.from("robot_guide_tasks").update({
      status: result.status,
      updated_at: new Date().toISOString(),
    }).eq("id", _activeGuideTaskId).then(() => null);
  }
  return result;
}

async function finishRobotGuide(status = "completed") {
  const targetIp = _cachedLocalIp || _defaultIpForMode();
  const action = status === "cancelled" ? "cancel" : "complete";
  const result = await sendDirectCommand(targetIp, `/guide/${action}`, {}, 1200);
  if (_activeGuideTaskId) {
    const taskId = _activeGuideTaskId;
    _activeGuideTaskId = null;
    _lastPersistedGuideStatus = status;
    supabaseClient.from("robot_guide_tasks").update({
      status,
      updated_at: new Date().toISOString(),
    }).eq("id", taskId).then(() => null);
  }
  return result;
}

async function fetchAiStatus() {
  // 로봇 자체 추론 상태(backend/fps/지연/탐지목록)를 직접 읽는다.
  const ip = _cachedLocalIp || _defaultIpForMode();
  const url = `http://${ip}:8080/ai/status`;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1200);
    const resp = await fetch(url, { method: "GET", mode: "cors", signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

async function verifyCheckoutItem(item) {
  const host = window.location.hostname || "127.0.0.1";
  const query = new URLSearchParams({
    expected_name: item?.name || "",
    expected_category: item?.item_type || item?.category || "",
  });
  try {
    const verifyOnce = async () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1800);
      const resp = await fetch(`http://${host}:8081/checkout/verify?${query}`, {
        method: "GET", mode: "cors", signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!resp.ok) return null;
      return await resp.json();
    };
    const first = await verifyOnce();
    if (first?.verdict !== "blocked") return first;
    await new Promise((resolve) => setTimeout(resolve, 320));
    const second = await verifyOnce();
    return second?.verdict === "blocked" ? second : { verdict: "inconclusive", reason: "재검사에서 이상 미확인" };
  } catch {
    // AI 서버 장애가 대여 시스템 전체를 막지는 않는다. QR/RPC 검증은 계속 적용된다.
    return { verdict: "unavailable", reason: "AI 서버 연결 실패" };
  }
}

async function toggleIntruderGuard() {
  const host = window.location.hostname || "127.0.0.1";
  const url = `http://${host}:8081/toggle_guard`;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);
    const resp = await fetch(url, { method: "GET", mode: "cors", signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return await resp.json();
  } catch (err) {
    return { status: "error", message: err.message || String(err) };
  }
}

// 부저 경보. 실패하면 반드시 throw한다 — 예전에는 두 시도가 다 실패해도
// {status:"ok"}를 돌려줘서, 로봇에 부저 코드가 아예 없던 시절에도 웹에는
// 초록 성공 토스트가 떴다. 안전 기능에서 거짓 성공은 위험하다.
async function triggerRemoteBuzzer(localIp) {
  const targetIp = _cachedLocalIp || localIp || _defaultIpForMode();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const resp = await fetch(`http://${targetIp}:8080/buzzer`, {
      method: "GET",
      mode: "cors",
      signal: controller.signal,
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(body.message || `로봇이 ${resp.status}로 응답했습니다.`);
    }
    return body;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("로봇이 응답하지 않습니다. Wi-Fi 연결을 확인해주세요.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// 경광등(triggerRemoteSiren)은 제거했다 — 이 보드의 LED는 표시등 수준이라
// 실내 경보로 인식이 안 된다는 실기기 확인 결과(2026-08-27). 경보는 부저로만 한다.

window.LabBotRobotConsole = {
  cameraSnapshotUrl,
  fetchRobotCommand,
  fetchRobotIp,
  getDirectStreamUrl,
  getAiVisionStreamUrl,
  checkStreamHealth,
  fetchCameraAngle,
  fetchTelemetry,
  fetchNightGuardStatus,
  configureNightGuard,
  triggerNightGuardInvestigation,
  triggerQrScan,
  startRobotGuide,
  fetchRobotGuideStatus,
  finishRobotGuide,
  fetchAiStatus,
  verifyCheckoutItem,
  toggleIntruderGuard,
  triggerRemoteBuzzer,
  setRobotCommand,
  setCameraAngle,
  setTargetMode,
  getTargetMode,
};
