// 좌표 순찰 패널
// ===========================================================================
// 실물은 현장 보정 좌표, Isaac은 저장된 전체 연구실 경로를 따라 순찰한다.
//
// 지도를 그리는 이유는 숫자만으로는 "제대로 돌고 있나"를 알 수 없기 때문이다.
// 계획된 경로(점선)와 실제 지나온 자취(실선)를 겹쳐 그리면 어디서 얼마나
// 틀어졌는지 한눈에 보인다. 좌표가 (0,0) 으로 돌아왔다는 숫자뿐 아니라 실제
// 이동 자취가 계획 경로를 따르는지도 함께 확인한다.

(function setupCoordinatePatrol() {
  const canvas = document.getElementById("patrolMap");
  const startBtn = document.getElementById("patrolStartBtn");
  const stopBtn = document.getElementById("patrolStopBtn");
  const envSel = document.getElementById("patrolEnv");
  const autoSel = document.getElementById("patrolAutoInterval");
  const continuousOption = document.getElementById("patrolContinuousOption");
  const badge = document.getElementById("patrolStatusBadge");
  const routeText = document.getElementById("patrolRouteText");
  const poseText = document.getElementById("patrolPoseText");
  const legText = document.getElementById("patrolLegText");
  const nextText = document.getElementById("patrolNextText");
  const msgEl = document.getElementById("patrolMessage");
  if (!canvas || !startBtn) return;

  const api = () => window.LabBotRobotConsole || {};
  const PAD = 28; // 지도 가장자리 여백(px)
  let route = []; // 계획된 경로 [{x_cm, y_cm, name}]
  let trail = []; // 실제 지나온 자취
  let pollTimer = null;
  let autoTimer = null;
  let nextRunAt = null;
  let routeIsOfflinePreview = false;
  const MAP_CACHE_PREFIX = "labbot_patrol_map_";

  // 로봇이 보내는 영어 phase 를 그대로 보여주면 안 된다. 사람이 읽는 말로 바꾼다.
  const PHASE_LABEL = {
    idle: "대기",
    starting: "시작 중",
    turning: "방향 잡는 중",
    driving: "주행 중",
    blocked: "장애물 앞 감속",
    arrived: "지점 도착",
    done: "완료",
    aborted: "중단됨",
    error: "오류",
    blocked_stop: "막혀서 중단",
    paused_for_guide: "물품 안내 우선",
    paused: "일시 정지",
    returning: "대기 자리 복귀 중",
    emergency_stop: "강제정지",
  };

  function setBadge(text, tone) {
    if (!badge) return;
    badge.className = "badge " + tone;
    badge.innerHTML = '<span class="badge-dot"></span>' + text;
  }

  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  // --- 지도 그리기 ---------------------------------------------------------
  // 배율을 매번 다시 잡는다. 경로 크기가 방마다 다르고(190x100, 200x110 …)
  // 자취가 경로 밖으로 삐져나갈 수도 있어서 고정 배율로는 안 담긴다.
  function project(pts) {
    const all = pts.filter(function (p) {
      return Number.isFinite(p.x) && Number.isFinite(p.y);
    });
    if (!all.length) return null;
    const xs = all.map(function (p) { return p.x; });
    const ys = all.map(function (p) { return p.y; });
    const minX = Math.min.apply(null, xs.concat([0]));
    const maxX = Math.max.apply(null, xs.concat([0]));
    const minY = Math.min.apply(null, ys.concat([0]));
    const maxY = Math.max.apply(null, ys.concat([0]));
    const w = Math.max(maxX - minX, 1);
    const h = Math.max(maxY - minY, 1);
    const scale = Math.min(
      (canvas.width - PAD * 2) / w,
      (canvas.height - PAD * 2) / h
    );
    return function (p) {
      return {
        // y 는 위가 + 이므로 화면 좌표로 뒤집는다.
        px: PAD + (p.x - minX) * scale,
        py: canvas.height - PAD - (p.y - minY) * scale,
      };
    };
  }

  function drawMap(pose) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const plan = route.map(function (w) {
      return { x: w.x_cm, y: w.y_cm };
    });
    const pts = plan.concat(trail);
    if (pose) pts.push({ x: pose.x, y: pose.y });
    const to = project(pts);
    if (!to) return;

    const ink = css("--text", "#1f2328");
    const faint = css("--text-faint", "#8a8f98");
    const accent = css("--primary", "#2f6fed");

    // 계획된 경로 — 점선 웨이포인트
    if (plan.length > 1) {
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = faint;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      plan.concat([plan[0]]).forEach(function (p, i) {
        const q = to(p);
        if (i === 0) ctx.moveTo(q.px, q.py);
        else ctx.lineTo(q.px, q.py);
      });
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.font = "11px system-ui, sans-serif";
      plan.forEach(function (p, i) {
        const q = to(p);
        ctx.fillStyle = faint;
        ctx.beginPath();
        ctx.arc(q.px, q.py, 4, 0, Math.PI * 2);
        ctx.fill();
        const label = (route[i] && route[i].name) || String(i);
        ctx.fillText(label, q.px + 7, q.py - 6);
      });
    }

    // 실제 지나온 자취 — 실선
    if (trail.length > 1) {
      ctx.strokeStyle = accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      trail.forEach(function (p, i) {
        const q = to(p);
        if (i === 0) ctx.moveTo(q.px, q.py);
        else ctx.lineTo(q.px, q.py);
      });
      ctx.stroke();
    }

    // 로봇 — 현재 위치와 바라보는 방향
    if (pose) {
      const q = to({ x: pose.x, y: pose.y });
      ctx.fillStyle = accent;
      ctx.beginPath();
      ctx.arc(q.px, q.py, 6, 0, Math.PI * 2);
      ctx.fill();
      if (Number.isFinite(pose.heading)) {
        const rad = (pose.heading * Math.PI) / 180;
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(q.px, q.py);
        ctx.lineTo(q.px + Math.cos(rad) * 16, q.py - Math.sin(rad) * 16);
        ctx.stroke();
      }
    }

    // 출발점. 순찰은 늘 여기로 돌아와야 하므로 따로 표시한다.
    const home = to({ x: 0, y: 0 });
    ctx.strokeStyle = ink;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(home.px - 5, home.py - 5, 10, 10);
  }

  // --- 상태 ---------------------------------------------------------------

  function readCachedRoute(env) {
    try {
      const cached = JSON.parse(localStorage.getItem(MAP_CACHE_PREFIX + env) || "null");
      return cached && Array.isArray(cached.waypoints) ? cached : null;
    } catch {
      return null;
    }
  }

  function saveCachedRoute(env, data) {
    try {
      localStorage.setItem(MAP_CACHE_PREFIX + env, JSON.stringify(data));
    } catch {}
  }

  async function loadOfflineRoute(env) {
    const cached = readCachedRoute(env);
    if (cached) return { ...cached, offlinePreview: true, cachedPreview: true };
    if (env !== "real") return null;
    try {
      const response = await fetch("data/real_patrol_map.json", { cache: "no-store" });
      if (!response.ok) return null;
      return { ...(await response.json()), offlinePreview: true, cachedPreview: false };
    } catch {
      return null;
    }
  }

  async function loadRoute() {
    const env = (envSel && envSel.value) || "real";
    let data = api().fetchPatrolMap ? await api().fetchPatrolMap(env) : null;
    if (data && Array.isArray(data.waypoints)) {
      saveCachedRoute(env, data);
      routeIsOfflinePreview = false;
    } else {
      data = await loadOfflineRoute(env);
      routeIsOfflinePreview = !!data;
    }
    if (!data || !data.waypoints) {
      route = [];
      routeText.textContent = "연결 없음";
      msgEl.textContent = env === "isaac"
        ? "Isaac Sim을 실행하면 저장된 전체 연구실 순찰 경로가 표시됩니다."
        : "실물 로봇 연결을 확인해주세요.";
      drawMap(null);
      return;
    }
    route = data.waypoints;
    const xs = route.map(function (w) { return w.x_cm; });
    const ys = route.map(function (w) { return w.y_cm; });
    const w = Math.max.apply(null, xs) - Math.min.apply(null, xs);
    const h = Math.max.apply(null, ys) - Math.min.apply(null, ys);
    const routeLabel = env === "isaac"
      ? (data.name || "순찰") + " · " + (w / 100).toFixed(1) + " × " + (h / 100).toFixed(1) + "m · " + route.length + "지점"
      : (data.name || "순찰") + " · " + Math.round(w) + " × " + Math.round(h) + "cm";
    routeText.textContent = routeIsOfflinePreview ? "오프라인 미리보기 · " + routeLabel : routeLabel;
    msgEl.textContent = routeIsOfflinePreview
      ? (data.cachedPreview
        ? "실물 로봇 연결 대기 중 · 마지막으로 받은 저장 경로를 표시합니다."
        : "실물 로봇 연결 대기 중 · 로봇의 기본 순찰 경로를 표시합니다.")
      : (data.description || (env === "isaac"
        ? "입구 보급공간부터 실험실·보관실을 순회한 뒤 대기 위치로 복귀합니다."
        : "실물 로봇의 저장 경로를 사용합니다."));
    drawMap(null);
  }

  async function poll() {
    const env = (envSel && envSel.value) || "real";
    const st = api().fetchPatrolStatus ? await api().fetchPatrolStatus(2000, env) : null;
    if (!st) {
      setBadge("연결 없음", "badge-st-open");
      poseText.textContent = "—";
      return;
    }
    const running = !!st.running;
    // 바퀴가 잠겨 있으면 그걸 먼저 알린다. 이게 안 보이면 "순찰 버튼을 눌러도
    // 아무 일이 없다"로만 보이고 이유를 알 수 없다.
    if (st.motion_locked) {
      setBadge("바퀴 잠김" + (st.motion_lock_reason ? " · " + st.motion_lock_reason : ""),
               "badge-st-open");
    } else {
      setBadge(
        PHASE_LABEL[st.phase] || st.phase || "대기",
        running ? "badge-st-progress" : "badge-st-open"
      );
    }

    if (Number.isFinite(st.x_cm) && Number.isFinite(st.y_cm)) {
      poseText.textContent =
        "(" + Math.round(st.x_cm) + ", " + Math.round(st.y_cm) + ")cm · " +
        Math.round(st.heading_deg || 0) + "도";
      const last = trail[trail.length - 1];
      // 같은 점을 계속 쌓지 않는다. 1cm 넘게 움직였을 때만 자취에 넣는다.
      if (!last || Math.hypot(last.x - st.x_cm, last.y - st.y_cm) > 1) {
        trail.push({ x: st.x_cm, y: st.y_cm });
        if (trail.length > 3000) trail.splice(0, 1500);
      }
    }

    const lapText = st.laps === 0
      ? (st.lap || 1) + "바퀴째 · 연속"
      : (st.lap || 1) + "/" + (st.laps || 1) + "바퀴";
    legText.textContent = running
      ? (st.leg || 0) + "/" + (st.legs || "?") + " 지점 · " + lapText
      : (st.phase === "done" ? "순찰 완료" : "—");
    if (st.motion_locked) {
      msgEl.textContent = "바퀴가 잠겨 있어 로봇이 움직이지 않습니다"
        + (st.motion_lock_reason ? ` (${st.motion_lock_reason})` : "")
        + " · 관리자가 잠금을 풀면 순찰과 배달이 다시 동작합니다.";
    } else if (st.message) {
      msgEl.textContent = st.message;
    }

    if (env === "isaac" && autoSel) {
      if (st.running && st.laps === 0 && st.control_mode === "patrol") {
        autoSel.value = "-1";
        nextRunAt = null;
        nextText.textContent = "중지할 때까지 연속";
      } else if (Number(st.repeat_minutes) > 0) {
        autoSel.value = String(st.repeat_minutes);
        nextRunAt = Number(st.next_run_at) > 0 ? Number(st.next_run_at) * 1000 : null;
        nextText.textContent = nextRunAt
          ? Math.max(1, Math.ceil((nextRunAt - Date.now()) / 60000)) + "분 뒤"
          : "현재 순찰 후 반복";
      } else {
        autoSel.value = "0";
        nextRunAt = null;
        nextText.textContent = st.running ? "1회 후 정지" : "자동반복 꺼짐";
      }
    }

    drawMap(
      Number.isFinite(st.x_cm)
        ? { x: st.x_cm, y: st.y_cm, heading: st.heading_deg }
        : null
    );

    if (!running && pollTimer && !(env === "isaac" && Number(st.repeat_minutes) > 0)) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(poll, 1000);
    poll();
  }

  async function runPatrol() {
    const env = (envSel && envSel.value) || "real";
    trail = [];
    const repeatPolicy = Number((autoSel && autoSel.value) || 0);
    // Isaac의 연속 모드만 무제한(0바퀴=제한 없음)이고 나머지는 한 바퀴씩 돈다.
    const laps = env === "isaac" && repeatPolicy === -1 ? 0 : 1;
    const r = api().startPatrol ? await api().startPatrol(env, laps) : null;
    if (!r) {
      if (window.LabBotToast) window.LabBotToast.error("로봇에 연결할 수 없습니다.");
      return;
    }
    if (r.error) {
      if (window.LabBotToast) window.LabBotToast.error("순찰 시작 실패: " + r.error);
      return;
    }
    if (r.warning) {
      msgEl.textContent = r.warning;
      console.warn("[patrol]", r.warning);
    }
    if (window.LabBotToast) {
      window.LabBotToast.success(
        (env === "isaac" && laps === 0 ? "연속 자동순찰 시작 — " : "순찰 시작 — ") + (r.map || env)
      );
    }
    startPolling();
  }

  // --- 자동 반복 ------------------------------------------------------------
  // 정해둔 간격마다 스스로 한 바퀴 돈다. 이미 순찰 중이면 이번 차례를 건너뛴다 -
  // 겹쳐 시작하면 로봇이 지금 자리를 (0,0) 으로 새로 잡아버려서 진행 중이던
  // 바퀴의 좌표가 통째로 어긋난다.
  async function applyAuto(sendToServer = true) {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
    const env = (envSel && envSel.value) || "real";
    if (env === "isaac") {
      if (continuousOption) continuousOption.hidden = false;
      if (autoSel) autoSel.disabled = false;
      const minutes = Number((autoSel && autoSel.value) || 0);
      nextRunAt = null;
      nextText.textContent = minutes === -1
        ? "중지할 때까지 연속"
        : (minutes > 0 ? minutes + "분 간격" : "1회 후 정지");
      if (sendToServer && api().configurePatrolRepeat) {
        const result = await api().configurePatrolRepeat(env, minutes);
        if (!result) {
          if (window.LabBotToast) window.LabBotToast.error("Isaac 자동반복 설정을 보내지 못했습니다.");
          return;
        }
        if (result.error) {
          if (window.LabBotToast) window.LabBotToast.error("자동반복 설정 실패: " + result.error);
          return;
        }
        if (Number(result.next_run_at) > 0) nextRunAt = Number(result.next_run_at) * 1000;
        startPolling();
      }
      return;
    }
    if (continuousOption) continuousOption.hidden = true;
    if (autoSel) {
      autoSel.disabled = false;
      autoSel.title = "";
      if (autoSel.value === "-1") autoSel.value = "0";
    }
    const minutes = Number((autoSel && autoSel.value) || 0);
    if (!minutes) {
      nextRunAt = null;
      nextText.textContent = "자동 반복 꺼짐";
      return;
    }
    const ms = minutes * 60 * 1000;
    nextRunAt = Date.now() + ms;
    autoTimer = setInterval(async function () {
      const env = (envSel && envSel.value) || "real";
      const st = api().fetchPatrolStatus ? await api().fetchPatrolStatus(2000, env) : null;
      if (st && st.running) return; // 아직 돌고 있으면 넘긴다
      nextRunAt = Date.now() + ms;
      runPatrol();
    }, ms);
    nextText.textContent = minutes + "분 뒤";
  }

  setInterval(function () {
    if (!nextRunAt) return;
    const left = Math.max(0, nextRunAt - Date.now());
    nextText.textContent = Math.ceil(left / 60000) + "분 뒤";
  }, 15000);

  startBtn.addEventListener("click", runPatrol);
  if (stopBtn) {
    stopBtn.addEventListener("click", async function () {
      const env = (envSel && envSel.value) || "real";
      if (api().stopPatrol) await api().stopPatrol(env);
      if (autoSel) autoSel.value = "0";
      await applyAuto(false);
      if (window.LabBotToast) window.LabBotToast.success("순찰을 중지했습니다.");
      poll();
    });
  }
  if (envSel) {
    envSel.addEventListener("change", function () {
      trail = [];
      applyAuto(false);
      loadRoute();
      startPolling();
    });
  }
  if (autoSel) autoSel.addEventListener("change", function () { applyAuto(true); });

  applyAuto(false);
  loadRoute();
  startPolling();
})();
