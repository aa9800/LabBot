// LabBot - 관리자 화면 스크립트 (Supabase items 테이블 연동)

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

  const damageTableBody = document.getElementById("damageTableBody");
  const damageEmptyState = document.getElementById("damageEmptyState");

  const safetyTableBody = document.getElementById("safetyTableBody");
  const safetyDetail = document.getElementById("safetyDetail");
  const safetyStatusFilter = document.getElementById("safetyStatusFilter");

  const auditChecklistBody = document.getElementById("auditChecklistBody");
  const auditSelectedCount = document.getElementById("auditSelectedCount");
  const auditSelectAllBtn = document.getElementById("auditSelectAllBtn");
  const auditSubmitBtn = document.getElementById("auditSubmitBtn");
  const auditSessionTableBody = document.getElementById("auditSessionTableBody");
  const auditDetail = document.getElementById("auditDetail");

  const locationSelect = document.getElementById("newItemLocation");
  const minimumInput = document.getElementById("newItemMinimum");
  const unitInput = document.getElementById("newItemUnit");
  const storageInput = document.getElementById("newItemStorage");
  const expiresInput = document.getElementById("newItemExpires");
  const notesInput = document.getElementById("newItemNotes");

  function renderCategoryOptions() {
    categorySelect.innerHTML = LAB_CATEGORIES.filter((c) => c.key !== "all")
      .map((c) => `<option value="${c.key}">${c.label}</option>`)
      .join("");
  }

  function renderLocationOptions() {
    locationSelect.innerHTML = window.LabBotItems.LAB_LOCATIONS.map((loc) => `<option value="${loc}">${loc}</option>`).join(
      ""
    );
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

    const { escapeHtml, computeStockStatus, STOCK_STATUS_FULL_LABEL, STOCK_STATUS_BADGE_CLASS } = window.LabBotItems;

    items.forEach((item) => {
      const statusKey = computeStockStatus(item);
      const statusLabel = STOCK_STATUS_FULL_LABEL[statusKey];
      const badgeClass = STOCK_STATUS_BADGE_CLASS[statusKey];
      const isMaintenance = item.manual_status === "MAINTENANCE";

      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${escapeHtml(item.name)}</td>
        <td>${escapeHtml(item.categoryLabel)}</td>
        <td>${escapeHtml(item.location)}</td>
        <td class="qr-cell">
          <canvas class="qr-thumb" title="클릭하면 인쇄용 크기로 다운로드됩니다" data-qr="${escapeHtml(item.qr_code)}"></canvas>
          <span class="mono">${escapeHtml(item.qr_code)}</span>
        </td>
        <td><span class="badge ${badgeClass}"><span class="badge-dot"></span>${statusLabel}</span></td>
        <td><input type="number" class="stock-input" min="0" value="${item.available_qty}" data-field="available" /></td>
        <td><input type="number" class="stock-input" min="0" value="${item.total_qty}" data-field="total" /></td>
        <td><input type="number" class="stock-input" min="0" value="${item.minimum_qty ?? ""}" placeholder="-" data-field="minimum" /></td>
        <td style="text-align:center;"><input type="checkbox" data-field="maintenance" ${isMaintenance ? "checked" : ""} /></td>
        <td class="stock-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="save">저장</button>
          <button type="button" class="btn btn-danger btn-sm" data-action="delete">삭제</button>
        </td>
      `;

      // 물품마다 실제로 스캔 가능한 QR 이미지를 그려준다 — qr_code 문자열 자체는 DB 트리거가
      // 물품 등록 시 자동 발급하고(items_set_qr_code), 여기서는 그 문자열을 이미지로 렌더링만 한다.
      const qrCanvas = row.querySelector(".qr-thumb");
      window.QRCode.toCanvas(qrCanvas, item.qr_code, { width: 48, margin: 1 }, (err) => {
        if (err) console.warn("LabBot: QR 코드 렌더링 실패", err);
      });
      qrCanvas.addEventListener("click", () => {
        window.QRCode.toDataURL(item.qr_code, { width: 480, margin: 2 }, (err, url) => {
          if (err) {
            alert("QR 코드 생성에 실패했습니다.");
            return;
          }
          const link = document.createElement("a");
          link.href = url;
          link.download = `${item.qr_code}.png`;
          link.click();
        });
      });

      row.querySelector('[data-action="save"]').addEventListener("click", async (e) => {
        const button = e.currentTarget;
        const availableInput = row.querySelector('[data-field="available"]');
        const totalInput = row.querySelector('[data-field="total"]');
        const minimumInputEl = row.querySelector('[data-field="minimum"]');
        const maintenanceInput = row.querySelector('[data-field="maintenance"]');

        const available_qty = Number(availableInput.value);
        const total_qty = Number(totalInput.value);
        const minimum_qty = minimumInputEl.value === "" ? null : Number(minimumInputEl.value);

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
          await window.LabBotItems.updateItemDetails(item.id, {
            minimum_qty,
            storage_condition: item.storage_condition,
            expires_at: item.expires_at,
            notes: item.notes,
            manual_status: maintenanceInput.checked ? "MAINTENANCE" : null,
          });
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
          <td>${window.LabBotItems.escapeHtml(row.user)}</td>
          <td>${window.LabBotItems.escapeHtml(row.item)}</td>
          <td><span class="badge badge-${row.badgeKey}"><span class="badge-dot"></span>${row.type}</span></td>
          <td>${new Date(row.time).toLocaleString("ko-KR")}</td>
        </tr>
      `
      )
      .join("");
  }

  // ---------- 파손 신고 목록 ----------
  async function renderDamageTable() {
    let reports;
    try {
      reports = await window.LabBotDamage.fetchAllDamageReports();
    } catch (err) {
      alert("파손 신고 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const { escapeHtml } = window.LabBotItems;
    const { DAMAGE_SEVERITY_LABEL, DAMAGE_SEVERITY_BADGE_CLASS, DAMAGE_STATUS_LABEL } = window.LabBotDamage;

    damageEmptyState.style.display = reports.length === 0 ? "block" : "none";
    damageTableBody.innerHTML = reports
      .map((r) => {
        const itemName = (r.items && r.items.name) || "삭제된 물품";
        const reporterName = (r.profiles && r.profiles.name) || "알 수 없음";

        let resultCell;
        if (r.status === "analyzed" && r.severity) {
          const badgeClass = DAMAGE_SEVERITY_BADGE_CLASS[r.severity] || "badge-sev-low";
          const label = DAMAGE_SEVERITY_LABEL[r.severity] || r.severity;
          resultCell = `<span class="badge ${badgeClass}"><span class="badge-dot"></span>${escapeHtml(label)}</span>`;
        } else if (r.status === "failed") {
          resultCell = `<span class="badge badge-st-closed"><span class="badge-dot"></span>분석 실패</span>`;
        } else {
          resultCell = `<span class="badge badge-pending"><span class="badge-dot"></span>${escapeHtml(DAMAGE_STATUS_LABEL.pending)}</span>`;
        }

        let detailText = "-";
        if (r.ai_result) {
          try {
            const parsed = JSON.parse(r.ai_result);
            detailText = parsed.error
              ? `오류: ${parsed.error}`
              : `${parsed.summary || ""}${parsed.recommended_action ? " → " + parsed.recommended_action : ""}`;
          } catch {
            detailText = r.ai_result;
          }
        }

        return `
        <tr>
          <td>${escapeHtml(itemName)}</td>
          <td>${escapeHtml(reporterName)}</td>
          <td class="mono">${new Date(r.created_at).toLocaleString("ko-KR")}</td>
          <td>${r.photo_url ? `<a href="${escapeHtml(r.photo_url)}" target="_blank" rel="noopener">사진 보기</a>` : "-"}</td>
          <td>${resultCell}</td>
          <td>${escapeHtml(detailText)}</td>
        </tr>
      `;
      })
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
      <div class="safety-detail-row"><span class="label">출처</span><span>${window.LabBotItems.escapeHtml(event.source)}</span></div>
      <div class="safety-detail-row"><span class="label">감지시각</span><span class="mono">${new Date(event.detected_at).toLocaleString("ko-KR")}</span></div>
      <div class="safety-detail-row"><span class="label">감지 메모</span><span>${window.LabBotItems.escapeHtml(event.note) || "-"}</span></div>
      ${event.resolved_at ? `<div class="safety-detail-row"><span class="label">조치 메모</span><span>${window.LabBotItems.escapeHtml(event.resolution_note) || "-"}</span></div>` : ""}

      <p class="label" style="margin-top: 14px;">처리 이력</p>
      <ul class="safety-log-list">
        ${logs.length === 0 ? "<li>아직 처리 이력이 없습니다.</li>" : logs.map((l) => `<li>[${new Date(l.created_at).toLocaleString("ko-KR")}] ${window.LabBotItems.escapeHtml(l.actor)} — ${window.LabBotItems.escapeHtml(window.LabBotSafety.SAFETY_STATUS_LABEL[l.action] || l.action)}${l.note ? " (" + window.LabBotItems.escapeHtml(l.note) + ")" : ""}</li>`).join("")}
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

  function updateAuditSelectedCount() {
    const boxes = auditChecklistBody.querySelectorAll(".audit-check");
    const checked = auditChecklistBody.querySelectorAll(".audit-check:checked");
    auditSelectedCount.textContent = `${checked.length}/${boxes.length}개 확인함`;
  }

  async function renderAuditChecklist() {
    let items;
    try {
      items = await loadAllItems();
    } catch (err) {
      alert("물품 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    auditChecklistBody.innerHTML = items
      .map(
        (item) => `
        <tr>
          <td><input type="checkbox" class="audit-check" value="${item.id}" /></td>
          <td>${window.LabBotItems.escapeHtml(item.name)}</td>
          <td>${window.LabBotItems.escapeHtml(item.categoryLabel)}</td>
          <td>${window.LabBotItems.escapeHtml(item.location)}</td>
        </tr>
      `
      )
      .join("");

    auditChecklistBody.querySelectorAll(".audit-check").forEach((cb) => {
      cb.addEventListener("change", updateAuditSelectedCount);
    });
    updateAuditSelectedCount();
  }

  auditSelectAllBtn.addEventListener("click", () => {
    const boxes = auditChecklistBody.querySelectorAll(".audit-check");
    const allChecked = [...boxes].every((cb) => cb.checked);
    boxes.forEach((cb) => (cb.checked = !allChecked));
    updateAuditSelectedCount();
  });

  auditSubmitBtn.addEventListener("click", async () => {
    const confirmedIds = [...auditChecklistBody.querySelectorAll(".audit-check:checked")].map((cb) =>
      Number(cb.value)
    );
    const totalCount = auditChecklistBody.querySelectorAll(".audit-check").length;

    if (
      !confirm(
        `확인한 ${confirmedIds.length}/${totalCount}개 물품으로 실사를 제출하시겠습니까?\n체크하지 않은 나머지 물품은 전부 "미확인"으로 기록됩니다.`
      )
    ) {
      return;
    }

    auditSubmitBtn.disabled = true;
    try {
      await window.LabBotAudit.submitAudit(confirmedIds);
      await renderAuditSessions();
      alert("실사가 제출되었습니다.");
    } catch (err) {
      alert("실사 제출에 실패했습니다: " + (err.message || err));
    } finally {
      auditSubmitBtn.disabled = false;
    }
  });

  async function renderAuditSessions() {
    let sessions;
    try {
      sessions = await window.LabBotAudit.fetchAuditSessions();
    } catch (err) {
      alert("실사 이력을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    auditDetail.style.display = "none";

    if (sessions.length === 0) {
      auditSessionTableBody.innerHTML = `<tr><td colspan="5" class="mono" style="text-align:center; padding: 20px;">실사 이력이 없습니다.</td></tr>`;
      return;
    }

    auditSessionTableBody.innerHTML = "";
    sessions.forEach((s) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${s.performed_by}</td>
        <td class="mono">${new Date(s.started_at).toLocaleString("ko-KR")}</td>
        <td>${s.scanned_count}개</td>
        <td>${s.mismatch_count}개</td>
        <td><button type="button" class="btn btn-secondary btn-sm" data-action="detail">상세</button></td>
      `;
      row.querySelector('[data-action="detail"]').addEventListener("click", () => showAuditDetail(s.id));
      auditSessionTableBody.appendChild(row);
    });
  }

  async function showAuditDetail(sessionId) {
    let mismatches;
    try {
      mismatches = await window.LabBotAudit.fetchAuditMismatches(sessionId);
    } catch (err) {
      alert("실사 상세를 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    auditDetail.style.display = "block";
    auditDetail.innerHTML = `
      <p class="label">미확인 물품 (${mismatches.length}개)</p>
      <ul class="safety-log-list">
        ${
          mismatches.length === 0
            ? "<li>미확인 물품이 없습니다 — 전체 물품을 확인했습니다.</li>"
            : mismatches
                .map(
                  (m) =>
                    `<li>${(m.items && m.items.name) || "삭제된 물품"} (${(m.items && m.items.location) || "-"}) — ${m.note}</li>`
                )
                .join("")
        }
      </ul>
    `;
  }

  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const name = document.getElementById("newItemName").value.trim();
    const category = categorySelect.value;
    const location = locationSelect.value;
    const total_qty = Number(document.getElementById("newItemTotal").value);
    const minimum_qty = minimumInput.value === "" ? null : Number(minimumInput.value);
    const unit = unitInput.value.trim() || null;
    const storage_condition = storageInput.value.trim() || null;
    const expires_at = expiresInput.value || null;
    const notes = notesInput.value.trim();

    if (!name || !location || !Number.isFinite(total_qty) || total_qty < 1) {
      alert("모든 항목을 올바르게 입력해주세요.");
      return;
    }

    const submitBtn = addForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;

    try {
      await window.LabBotItems.createItem({
        name,
        category,
        location,
        total_qty,
        minimum_qty,
        unit,
        storage_condition,
        expires_at,
        notes,
      });
      addForm.reset();
      renderLocationOptions(); // reset()이 select 첫 옵션으로 되돌리므로 다시 채워준다
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
    renderLocationOptions();
    await renderStockTable();
    await renderHistoryTable();
    await renderDamageTable();
    await renderSafetyTable();
    await renderAuditChecklist();
    await renderAuditSessions();
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
