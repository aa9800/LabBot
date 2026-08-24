// LabBot - 관리자 화면 스크립트 (Supabase items 테이블 연동)
// TODO: 파손 신고 목록은 Supabase 연동 후 실제 데이터로 렌더링할 것

document.addEventListener("DOMContentLoaded", async () => {
  const gate = document.getElementById("adminGate");
  const panel = document.getElementById("adminPanel");
  const loginForm = document.getElementById("adminLoginForm");
  const loginError = document.getElementById("adminLoginError");
  const logoutBtn = document.getElementById("adminLogoutBtn");

  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  const addForm = document.getElementById("itemAddForm");
  const categorySelect = document.getElementById("newItemCategory");
  const stockTableBody = document.getElementById("stockTableBody");
  const historyTableBody = document.getElementById("historyTableBody");

  const safetyTableBody = document.getElementById("safetyTableBody");
  const safetyDetail = document.getElementById("safetyDetail");
  const safetyStatusFilter = document.getElementById("safetyStatusFilter");

  function renderCategoryOptions() {
    categorySelect.innerHTML = LAB_CATEGORIES.filter((c) => c.key !== "all")
      .map((c) => `<option value="${c.key}">${c.label}</option>`)
      .join("");
  }

  async function loadAllItems() {
    return window.LabBotItems.searchItems({});
  }

  async function renderStockTable() {
    let items;
    try {
      items = await loadAllItems();
    } catch (err) {
      alert("물품 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    stockTableBody.innerHTML = "";

    items.forEach((item) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${item.name}</td>
        <td>${item.categoryLabel}</td>
        <td>${item.location}</td>
        <td class="mono">${item.qr_code}</td>
        <td><input type="number" class="stock-input" min="0" value="${item.available_qty}" data-field="available" /></td>
        <td><input type="number" class="stock-input" min="0" value="${item.total_qty}" data-field="total" /></td>
        <td class="stock-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="save">저장</button>
          <button type="button" class="btn btn-danger btn-sm" data-action="delete">삭제</button>
        </td>
      `;

      row.querySelector('[data-action="save"]').addEventListener("click", async (e) => {
        const button = e.currentTarget;
        const availableInput = row.querySelector('[data-field="available"]');
        const totalInput = row.querySelector('[data-field="total"]');

        const available_qty = Number(availableInput.value);
        const total_qty = Number(totalInput.value);

        if (
          !Number.isFinite(available_qty) ||
          !Number.isFinite(total_qty) ||
          available_qty < 0 ||
          total_qty < 0
        ) {
          alert("재고 수량은 0 이상의 숫자여야 합니다.");
          return;
        }

        if (available_qty > total_qty) {
          alert("대여가능 수량은 총 수량을 넘을 수 없습니다.");
          return;
        }

        button.disabled = true;
        try {
          await window.LabBotItems.updateItemStock(item.id, { available_qty, total_qty });
        } catch (err) {
          alert(err.message || "재고 수정에 실패했습니다.");
        } finally {
          button.disabled = false;
        }
        await renderStockTable();
      });

      row.querySelector('[data-action="delete"]').addEventListener("click", async () => {
        if (!confirm(`"${item.name}"을(를) 삭제하시겠습니까?`)) return;

        try {
          await window.LabBotItems.deleteItem(item.id);
          await renderStockTable();
        } catch (err) {
          alert(err.message || "삭제에 실패했습니다.");
        }
      });

      stockTableBody.appendChild(row);
    });
  }

  async function renderHistoryTable() {
    let loans;
    try {
      loans = await window.LabBotRentals.fetchAllLoans();
    } catch (err) {
      alert("대여 이력을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const rows = [];

    loans.forEach((loan) => {
      const userName = (loan.profiles && loan.profiles.name) || "알 수 없음";
      const itemName = (loan.items && loan.items.name) || "삭제된 물품";
      const overdue = window.LabBotRentals.isOverdue(loan);

      rows.push({
        user: userName,
        item: itemName,
        type: overdue ? "대여중(연체)" : "대여",
        badgeKey: overdue ? "overdue" : "inuse",
        time: loan.borrowed_at,
      });
      if (loan.returned_at) {
        rows.push({ user: userName, item: itemName, type: "반납", badgeKey: "available", time: loan.returned_at });
      }
    });

    rows.sort((a, b) => new Date(b.time) - new Date(a.time));

    historyTableBody.innerHTML = rows
      .map(
        (row) => `
        <tr>
          <td>${row.user}</td>
          <td>${row.item}</td>
          <td><span class="badge badge-${row.badgeKey}"><span class="badge-dot"></span>${row.type}</span></td>
          <td>${new Date(row.time).toLocaleString("ko-KR")}</td>
        </tr>
      `
      )
      .join("");
  }

  function severityBadge(severity) {
    const label = LabBotSafety.SAFETY_SEVERITY_LABEL[severity] || severity;
    return `<span class="badge badge-sev-${severity.toLowerCase()}"><span class="badge-dot"></span>${label}</span>`;
  }

  function statusBadge(status) {
    const label = LabBotSafety.SAFETY_STATUS_LABEL[status] || status;
    return `<span class="badge badge-st-${status.toLowerCase()}"><span class="badge-dot"></span>${label}</span>`;
  }

  async function renderSafetyTable() {
    let events;
    try {
      events = await window.LabBotSafety.fetchSafetyEvents({ status: safetyStatusFilter.value });
    } catch (err) {
      alert("안전 이벤트를 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    safetyTableBody.innerHTML = "";

    if (events.length === 0) {
      safetyTableBody.innerHTML = `<tr><td colspan="6" class="mono" style="text-align:center; padding: 20px;">해당하는 안전 이벤트가 없습니다.</td></tr>`;
      return;
    }

    events.forEach((ev) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td class="mono">${ev.rule_id}</td>
        <td>${severityBadge(ev.severity)}</td>
        <td>${statusBadge(ev.status)}</td>
        <td>${ev.source}</td>
        <td class="mono">${new Date(ev.detected_at).toLocaleString("ko-KR")}</td>
        <td><button type="button" class="btn btn-secondary btn-sm" data-action="detail">상세</button></td>
      `;
      row.querySelector('[data-action="detail"]').addEventListener("click", () => showSafetyDetail(ev.id));
      safetyTableBody.appendChild(row);
    });
  }

  async function showSafetyDetail(id) {
    let event, logs;
    try {
      ({ event, logs } = await window.LabBotSafety.fetchSafetyEventDetail(id));
    } catch (err) {
      alert("상세 정보를 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const nextActions = window.LabBotSafety.SAFETY_NEXT_ACTIONS[event.status] || [];

    safetyDetail.style.display = "block";
    safetyDetail.innerHTML = `
      <div class="safety-detail-row"><span class="label">규칙</span><span class="mono">${event.rule_id}</span></div>
      <div class="safety-detail-row"><span class="label">심각도</span>${severityBadge(event.severity)}</div>
      <div class="safety-detail-row"><span class="label">상태</span>${statusBadge(event.status)}</div>
      <div class="safety-detail-row"><span class="label">출처</span><span>${event.source}</span></div>
      <div class="safety-detail-row"><span class="label">감지시각</span><span class="mono">${new Date(event.detected_at).toLocaleString("ko-KR")}</span></div>
      <div class="safety-detail-row"><span class="label">감지 메모</span><span>${event.note || "-"}</span></div>
      ${event.resolved_at ? `<div class="safety-detail-row"><span class="label">조치 메모</span><span>${event.resolution_note || "-"}</span></div>` : ""}

      <p class="label" style="margin-top: 14px;">처리 이력</p>
      <ul class="safety-log-list">
        ${logs.length === 0 ? "<li>아직 처리 이력이 없습니다.</li>" : logs.map((l) => `<li>[${new Date(l.created_at).toLocaleString("ko-KR")}] ${l.actor} — ${window.LabBotSafety.SAFETY_STATUS_LABEL[l.action] || l.action}${l.note ? " (" + l.note + ")" : ""}</li>`).join("")}
      </ul>

      ${
        nextActions.length > 0
          ? `
        <textarea class="safety-note-input" id="safetyNoteInput" placeholder="조치 메모 (선택 — 예: 담당자, 조치 내용)" rows="2"></textarea>
        <div class="safety-actions">
          ${nextActions
            .map(
              (a) =>
                `<button type="button" class="btn ${a.action === "FALSE_POSITIVE" ? "btn-secondary" : "btn-primary"} btn-sm" data-next="${a.action}">${a.label}</button>`
            )
            .join("")}
        </div>`
          : `<p class="mono" style="margin-top: 10px; color: var(--text-faint);">이미 종결된 이벤트라 더 이상 상태를 바꿀 수 없습니다.</p>`
      }
    `;

    safetyDetail.querySelectorAll("[data-next]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const nextStatus = btn.dataset.next;
        const note = document.getElementById("safetyNoteInput").value.trim();
        btn.disabled = true;
        try {
          const session = await window.LabBotAuth.getSession();
          await window.LabBotSafety.transitionSafetyEvent(id, {
            nextStatus,
            actorName: (session && session.name) || "관리자",
            note,
          });
          await renderSafetyTable();
          await showSafetyDetail(id);
        } catch (err) {
          alert("상태 변경에 실패했습니다: " + (err.message || err));
          btn.disabled = false;
        }
      });
    });
  }

  safetyStatusFilter.addEventListener("change", renderSafetyTable);

  // ---------- Robot Console (카메라 스냅샷 + 수동조작) ----------
  const robotCameraImg = document.getElementById("robotCameraImg");
  const robotModeBadge = document.getElementById("robotModeBadge");
  const robotAutoBtn = document.getElementById("robotAutoBtn");
  const driveButtons = document.querySelectorAll("[data-drive]");

  const DRIVE_VALUES = {
    forward: { speed: 70, turn: 0 },
    backward: { speed: -70, turn: 0 },
    left: { speed: 0, turn: -90 },
    right: { speed: 0, turn: 90 },
    stop: { speed: 0, turn: 0 },
  };

  function refreshRobotCamera() {
    robotCameraImg.src = window.LabBotRobotConsole.cameraSnapshotUrl();
  }

  async function refreshRobotModeBadge() {
    try {
      const cmd = await window.LabBotRobotConsole.fetchRobotCommand();
      const isManual = cmd.mode === "manual";
      robotModeBadge.className = `badge ${isManual ? "badge-st-in_progress" : "badge-st-resolved"}`;
      robotModeBadge.innerHTML = `<span class="badge-dot"></span>${isManual ? "수동조작 중" : "자동순찰 중"}`;
    } catch (err) {
      robotModeBadge.className = "badge badge-st-closed";
      robotModeBadge.innerHTML = `<span class="badge-dot"></span>연결 확인 필요`;
    }
  }

  driveButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const values = DRIVE_VALUES[btn.dataset.drive];
      try {
        await window.LabBotRobotConsole.setRobotCommand({ mode: "manual", ...values });
        await refreshRobotModeBadge();
      } catch (err) {
        alert("원격조작 명령을 보내지 못했습니다: " + (err.message || err));
      }
    });
  });

  robotAutoBtn.addEventListener("click", async () => {
    try {
      await window.LabBotRobotConsole.setRobotCommand({ mode: "auto", speed: 0, turn: 0 });
      await refreshRobotModeBadge();
    } catch (err) {
      alert("자동 모드로 전환하지 못했습니다: " + (err.message || err));
    }
  });

  let robotConsoleStarted = false;
  function startRobotConsolePolling() {
    if (robotConsoleStarted) return; // showPanel()이 여러 번 불려도 인터벌이 중복 생기지 않게
    robotConsoleStarted = true;
    refreshRobotCamera();
    refreshRobotModeBadge();
    setInterval(refreshRobotCamera, 2000);
    setInterval(refreshRobotModeBadge, 3000);
  }

  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const name = document.getElementById("newItemName").value.trim();
    const category = categorySelect.value;
    const location = document.getElementById("newItemLocation").value.trim();
    const total_qty = Number(document.getElementById("newItemTotal").value);

    if (!name || !location || !Number.isFinite(total_qty) || total_qty < 1) {
      alert("모든 항목을 올바르게 입력해주세요.");
      return;
    }

    const submitBtn = addForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;

    try {
      await window.LabBotItems.createItem({ name, category, location, total_qty });
      addForm.reset();
      await renderStockTable();
    } catch (err) {
      alert("물품 등록에 실패했습니다: " + (err.message || err));
    } finally {
      submitBtn.disabled = false;
    }
  });

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;

      tabButtons.forEach((b) => b.classList.remove("active"));
      tabPanels.forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      document.getElementById(`tab-${target}`).classList.add("active");
    });
  });

  async function showPanel() {
    gate.style.display = "none";
    panel.style.display = "block";
    renderCategoryOptions();
    await renderStockTable();
    await renderHistoryTable();
    await renderSafetyTable();
  }

  function showGate() {
    gate.style.display = "block";
    panel.style.display = "none";
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.style.display = "none";

    const email = document.getElementById("adminEmail").value.trim();
    const password = document.getElementById("adminPassword").value;

    try {
      await window.LabBotAuth.signIn({ email, password });
    } catch (err) {
      loginError.textContent = "관리자 계정 정보가 올바르지 않습니다.";
      loginError.style.display = "block";
      return;
    }

    const session = await window.LabBotAuth.getSession();
    if (!session || session.role !== "admin") {
      await window.LabBotAuth.signOut();
      loginError.textContent = "관리자 계정 정보가 올바르지 않습니다.";
      loginError.style.display = "block";
      return;
    }

    await showPanel();
  });

  logoutBtn.addEventListener("click", async () => {
    await window.LabBotAuth.signOut();
    if (window.LabBotNav) {
      window.LabBotNav.goTo("index.html");
    } else {
      window.location.href = "index.html";
    }
  });

  const session = await window.LabBotAuth.getSession();
  if (session && session.role === "admin") {
    await showPanel();
  } else {
    showGate();
  }
});
