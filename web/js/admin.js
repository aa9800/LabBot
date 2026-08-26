// LabBot - 관리자 화면 스크립트 (Supabase items 테이블 연동)

document.addEventListener("DOMContentLoaded", async () => {
  const forbidden = document.getElementById("adminForbidden");
  const panel = document.getElementById("adminPanel");

  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  const addForm = document.getElementById("itemAddForm");
  const categorySelect = document.getElementById("newItemCategory");
  const stockTableBody = document.getElementById("stockTableBody");
  const stockSearchInput = document.getElementById("stockSearch");
  const stockLocationFilter = document.getElementById("stockLocationFilter");
  const stockCategoryFilters = document.getElementById("stockCategoryFilters");
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

  const inquiryListEl = document.getElementById("inquiryList");
  const inquiryEmptyState = document.getElementById("inquiryEmptyState");
  const inquiryPaginationEl = document.getElementById("inquiryPagination");
  const INQUIRY_PAGE_SIZE = 10;
  let inquiryPage = 1;

  const userTableBody = document.getElementById("userTableBody");
  const userSearchInput = document.getElementById("userSearch");

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
    stockLocationFilter.innerHTML =
      `<option value="all">전체 위치</option>` +
      window.LabBotItems.LAB_LOCATIONS.map((loc) => `<option value="${loc}">${loc}</option>`).join("");
  }

  async function loadAllItems() {
    return window.LabBotItems.searchItems({});
  }

  // 재고표 검색·카테고리·위치 필터 — 61개 물품 전체가 한 표에 다 보여서 특정 물품을
  // 찾기 어렵다는 지적(GPT 리뷰)에 대응. 물품목록 페이지와 같은 방식으로 클라이언트에서
  // 걸러낸다(새 API 호출 없이 이미 불러온 목록에서 필터링).
  let stockSearchTerm = "";
  let stockActiveCategory = "all";
  let stockActiveLocation = "all";

  function filterStockItems(items) {
    const term = stockSearchTerm.trim().toLowerCase();
    return items.filter((item) => {
      if (term && !item.name.toLowerCase().includes(term)) return false;
      if (stockActiveCategory !== "all" && item.category !== stockActiveCategory) return false;
      if (stockActiveLocation !== "all" && item.location !== stockActiveLocation) return false;
      return true;
    });
  }

  let stockSearchDebounceTimer = null;
  stockSearchInput.addEventListener("input", () => {
    clearTimeout(stockSearchDebounceTimer);
    stockSearchDebounceTimer = setTimeout(() => {
      stockSearchTerm = stockSearchInput.value;
      renderStockTable();
    }, 300);
  });

  stockLocationFilter.addEventListener("change", () => {
    stockActiveLocation = stockLocationFilter.value;
    renderStockTable();
  });

  stockCategoryFilters.querySelectorAll(".category-filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      stockCategoryFilters.querySelectorAll(".category-filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      stockActiveCategory = btn.dataset.category;
      renderStockTable();
    });
  });

  // 표가 비어있는 채로 잠깐 보이는 대신, 로딩 중임을 알 수 있게 자리표시자 행을 먼저 보여준다.
  function renderStockSkeleton() {
    const COLUMN_COUNT = 10;
    stockTableBody.innerHTML = Array.from({ length: 5 })
      .map(
        () =>
          `<tr class="skeleton-row">${Array.from({ length: COLUMN_COUNT })
            .map(() => `<td><span class="skeleton-bar"></span></td>`)
            .join("")}</tr>`
      )
      .join("");
  }

  async function renderStockTable() {
    renderStockSkeleton();

    let items;
    try {
      items = await loadAllItems();
    } catch (err) {
      window.LabBotToast.error("물품 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    items = filterStockItems(items);

    stockTableBody.innerHTML = "";

    if (items.length === 0) {
      stockTableBody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">검색 결과가 없습니다.</td></tr>`;
      return;
    }

    const { escapeHtml, computeStockStatus, STOCK_STATUS_FULL_LABEL, STOCK_STATUS_BADGE_CLASS } = window.LabBotItems;

    items.forEach((item) => {
      const statusKey = computeStockStatus(item);
      const statusLabel = STOCK_STATUS_FULL_LABEL[statusKey];
      const badgeClass = STOCK_STATUS_BADGE_CLASS[statusKey];
      const isMaintenance = item.manual_status === "MAINTENANCE";
      const qrCode = window.LabBotItems.qrCodeOf(item);

      const row = document.createElement("tr");
      row.innerHTML = `
        <td data-label="물품명"${item.notes ? ` title="${escapeHtml(item.notes)}"` : ""}>${escapeHtml(item.name)}</td>
        <td data-label="카테고리">${escapeHtml(item.categoryLabel)}</td>
        <td data-label="위치">${escapeHtml(item.location)}</td>
        <td data-label="QR 코드" class="qr-cell">
          ${
            qrCode
              ? `<canvas class="qr-thumb" title="클릭하면 인쇄용 크기로 다운로드됩니다" data-qr="${escapeHtml(qrCode)}"></canvas>
          <span class="mono">${escapeHtml(qrCode)}</span>`
              : `<span class="mono" style="color: var(--text-faint);">-</span>`
          }
        </td>
        <td data-label="상태"><span class="badge ${badgeClass}"><span class="badge-dot"></span>${statusLabel}</span></td>
        <td data-label="대여가능"><input type="number" class="stock-input" min="0" value="${item.available_qty}" data-field="available" /></td>
        <td data-label="총 수량"><input type="number" class="stock-input" min="0" value="${item.total_qty}" data-field="total" /></td>
        <td data-label="최소수량"><input type="number" class="stock-input" min="0" value="${item.minimum_qty ?? ""}" placeholder="-" data-field="minimum" /></td>
        <td data-label="점검중" style="text-align:center;"><input type="checkbox" data-field="maintenance" ${isMaintenance ? "checked" : ""} /></td>
        <td data-label="작업" class="stock-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="save">저장</button>
          <button type="button" class="btn btn-secondary btn-sm" data-action="history">이력</button>
          <button type="button" class="btn btn-danger btn-sm" data-action="delete">삭제</button>
        </td>
      `;

      // 물품마다 실제로 스캔 가능한 QR 이미지를 그려준다 — qr_code 문자열 자체는 DB 트리거가
      // 물품 등록 시 자동 발급해 item_qr_codes에 넣고(items_create_qr_code, 관리자만 조회
      // 가능 — docs/labbot_schema.sql 24번 섹션), 여기서는 그 문자열을 이미지로 렌더링만 한다.
      const qrCanvas = row.querySelector(".qr-thumb");
      if (qrCanvas && qrCode) {
        window.QRCode.toCanvas(qrCanvas, qrCode, { width: 48, margin: 1 }, (err) => {
          if (err) console.warn("LabBot: QR 코드 렌더링 실패", err);
        });
        qrCanvas.addEventListener("click", () => {
          window.QRCode.toDataURL(qrCode, { width: 480, margin: 2 }, (err, url) => {
            if (err) {
              window.LabBotToast.error("QR 코드 생성에 실패했습니다.");
              return;
            }
            const link = document.createElement("a");
            link.href = url;
            link.download = `${qrCode}.png`;
            link.click();
          });
        });
      }

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
          window.LabBotToast.error("재고 수량은 0 이상의 숫자여야 합니다.");
          return;
        }

        if (available_qty > total_qty) {
          window.LabBotToast.error("대여가능 수량은 총 수량을 넘을 수 없습니다.");
          return;
        }

        // 재고 수량이 실제로 바뀐 경우에만 조정 이력을 남긴다 — 최소수량/점검중만 바꿨는데
        // "0/0 → 0/0" 같은 의미없는 이력 줄이 쌓이는 걸 막는다. 바뀐 경우엔 사유를 먼저 물어본다
        // (GPT 리뷰 지적 — "왜 바꿨는지"가 항상 빈 값이었음).
        const stockChanged = available_qty !== item.available_qty || total_qty !== item.total_qty;
        let adjustment = null;
        if (stockChanged) {
          adjustment = await promptStockAdjustmentReason(item, available_qty, total_qty);
          if (!adjustment) return; // 사유 입력 중 취소하면 저장 자체를 하지 않는다
        }

        button.disabled = true;
        try {
          if (stockChanged) {
            const session = await window.LabBotAuth.getSession();
            await window.LabBotStockAdjustments.adjustItemStock(item, {
              available_qty,
              total_qty,
              actorName: (session && session.name) || "관리자",
              reason: adjustment.reason,
              note: adjustment.note,
            });
          } else {
            await window.LabBotItems.updateItemStock(item.id, { available_qty, total_qty });
          }
          await window.LabBotItems.updateItemDetails(item.id, {
            minimum_qty,
            storage_condition: item.storage_condition,
            expires_at: item.expires_at,
            notes: item.notes,
            manual_status: maintenanceInput.checked ? "MAINTENANCE" : null,
          });
        } catch (err) {
          window.LabBotToast.error(err.message || "재고 수정에 실패했습니다.");
        } finally {
          button.disabled = false;
        }
        await renderStockTable();
      });

      row.querySelector('[data-action="history"]').addEventListener("click", () => showStockHistory(item));

      row.querySelector('[data-action="delete"]').addEventListener("click", async () => {
        if (!confirm(`"${item.name}"을(를) 삭제하시겠습니까?`)) return;

        try {
          await window.LabBotItems.deleteItem(item.id);
          await renderStockTable();
        } catch (err) {
          window.LabBotToast.error(err.message || "삭제에 실패했습니다.");
        }
      });

      stockTableBody.appendChild(row);
    });
  }

  // 재고 수량을 바꿀 때 "왜 바꿨는지" 고르게 하는 작은 모달. 확인을 누르면 {reason, note}를,
  // 취소하면 null을 돌려준다 — 호출한 쪽(저장 버튼 핸들러)이 null이면 저장 자체를 중단한다.
  function promptStockAdjustmentReason(item, available_qty, total_qty) {
    const { escapeHtml } = window.LabBotItems;
    const { STOCK_ADJUSTMENT_REASONS } = window.LabBotStockAdjustments;

    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      overlay.innerHTML = `
        <div class="modal-card">
          <h3 class="modal-title">재고 변경 사유 — ${escapeHtml(item.name)}</h3>
          <p class="modal-subtitle">
            대여가능 ${item.available_qty} → ${available_qty}, 총수량 ${item.total_qty} → ${total_qty}
          </p>
          <div class="modal-field">
            <label>사유</label>
            <select id="adjustReasonSelect" class="location-filter-select" style="width: 100%;">
              ${STOCK_ADJUSTMENT_REASONS.map((r) => `<option value="${r}">${r}</option>`).join("")}
            </select>
          </div>
          <div class="modal-field" id="adjustNoteField" style="display: none;">
            <label>메모</label>
            <textarea id="adjustNoteInput" placeholder="간단히 적어주세요"></textarea>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-action="cancel">취소</button>
            <button type="button" class="btn btn-primary btn-sm" data-action="confirm">확인</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const reasonSelect = overlay.querySelector("#adjustReasonSelect");
      const noteField = overlay.querySelector("#adjustNoteField");
      const noteInput = overlay.querySelector("#adjustNoteInput");

      // "기타"를 골랐을 때만 메모 입력칸을 보여준다 — 나머지 사유는 선택지 자체가 설명이라
      // 매번 메모까지 받을 필요는 없다.
      reasonSelect.addEventListener("change", () => {
        noteField.style.display = reasonSelect.value === "기타" ? "block" : "none";
      });

      const finish = (result) => {
        overlay.remove();
        resolve(result);
      };

      overlay.querySelector('[data-action="cancel"]').addEventListener("click", () => finish(null));
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) finish(null);
      });
      overlay.querySelector('[data-action="confirm"]').addEventListener("click", () => {
        finish({ reason: reasonSelect.value, note: noteInput.value.trim() });
      });
    });
  }

  // 재고 조정 이력 모달 — 파손 신고 모달(mypage.js)과 같은 방식으로, 열 때 body에
  // 붙였다가 닫으면 제거한다. 관리자 전용 화면이라 별도 페이지 없이 모달로 충분하다.
  async function showStockHistory(item) {
    const { escapeHtml } = window.LabBotItems;

    let history;
    try {
      history = await window.LabBotStockAdjustments.fetchStockAdjustments(item.id);
    } catch (err) {
      window.LabBotToast.error("재고 조정 이력을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card">
        <h3 class="modal-title">재고 조정 이력 — ${escapeHtml(item.name)}</h3>
        <p class="modal-subtitle">관리자가 대여가능/총 수량을 바꿀 때마다 자동으로 기록됩니다.</p>
        <ul class="safety-log-list">
          ${
            history.length === 0
              ? "<li>아직 조정 이력이 없습니다.</li>"
              : history
                  .map(
                    (h) => `
                <li>[${new Date(h.created_at).toLocaleString("ko-KR")}] ${escapeHtml(h.actor)} — ${escapeHtml(h.reason || "기타")}:
                  대여가능 ${h.previous_available} → ${h.new_available}, 총수량 ${h.previous_total} → ${h.new_total}
                  ${h.note ? `(${escapeHtml(h.note)})` : ""}</li>
              `
                  )
                  .join("")
          }
        </ul>
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="close">닫기</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.querySelector('[data-action="close"]').addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
  }

  async function renderHistoryTable() {
    let loans;
    try {
      loans = await window.LabBotRentals.fetchAllLoans();
    } catch (err) {
      window.LabBotToast.error("대여 이력을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const rows = [];

    loans.forEach((loan) => {
      const userName = (loan.profiles && loan.profiles.name) || "알 수 없음";
      const itemName = (loan.items && loan.items.name) || "삭제된 물품";
      const overdue = window.LabBotRentals.isOverdue(loan);

      // 예약중(로봇 안내를 아직 안 받았거나 QR 확인 전)은 "대여"나 "사용"으로 세지 않는다 —
      // 실제로 받아가거나 쓴 게 아니라서, 소모품/장비 구분보다 이 체크를 먼저 한다.
      if (loan.status === "예약중") {
        rows.push({ user: userName, item: itemName, type: "예약", badgeKey: "pending", time: loan.borrowed_at });
        return;
      }

      // 취소된 예약도 감사 이력으로 남긴다(행을 지우지 않는 원칙) — 재고에는 영향 없었던
      // 것처럼 보이지 않게 "취소" 한 줄로 명시.
      if (loan.status === "취소됨") {
        rows.push({ user: userName, item: itemName, type: "취소", badgeKey: "st-closed", time: loan.returned_at || loan.borrowed_at });
        return;
      }

      // 시약/소모품 "사용하기"는 대여-반납이 아니라 한 번에 끝나는 소모라서(예약 -> QR 확인
      // 시점에 바로 반납완료로 들어간다), 대여+반납 두 줄로 보이면 "빌렸다가 바로
      // 반납했나?" 헷갈린다. 소모품이면 "사용" 한 줄로만 보여준다.
      const isConsumableLoan = loan.items && window.LabBotRentals.isConsumable({ item_type: loan.items.category });

      if (isConsumableLoan) {
        const qtyLabel = loan.consumed_qty && loan.consumed_qty > 1 ? `사용(${loan.consumed_qty}개)` : "사용";
        rows.push({
          user: userName,
          item: itemName,
          type: qtyLabel,
          badgeKey: "available",
          // qr_confirmed_at은 실제로 QR을 스캔해 사용을 확정한 시각 — borrowed_at(예약 시각)보다
          // 이걸 우선 보여준다.
          time: loan.qr_confirmed_at || loan.borrowed_at,
        });
        return;
      }

      rows.push({
        user: userName,
        item: itemName,
        type: overdue ? "대여중(연체)" : "대여",
        badgeKey: overdue ? "overdue" : "inuse",
        // due_at은 QR로 실제 수령을 확인한 시점에 매겨지므로, 대여 시각도 그 시점(qr_confirmed_at)
        // 기준으로 보여준다 — borrowed_at은 예약 시각이라 실제 대여 시작 시각과 다를 수 있다.
        time: loan.qr_confirmed_at || loan.borrowed_at,
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
      window.LabBotToast.error("파손 신고 목록을 불러오지 못했습니다: " + (err.message || err));
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
          <td>${r.photo_path ? `<button type="button" class="link-btn" data-photo-path="${escapeHtml(r.photo_path)}">사진 보기</button>` : "-"}</td>
          <td>${resultCell}</td>
          <td class="damage-result-cell">${escapeHtml(detailText)}</td>
        </tr>
      `;
      })
      .join("");

    // 비공개 버킷이라 고정 URL을 만들어둘 수 없다 — 누를 때마다 서명 URL을 새로 발급해 새 탭으로 연다.
    damageTableBody.querySelectorAll("[data-photo-path]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const url = await window.LabBotDamage.getDamagePhotoUrl(btn.dataset.photoPath);
          window.open(url, "_blank", "noopener");
        } catch (err) {
          window.LabBotToast.error("사진을 불러오지 못했습니다: " + (err.message || err));
        } finally {
          btn.disabled = false;
        }
      });
    });
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
      window.LabBotToast.error("안전 이벤트를 불러오지 못했습니다: " + (err.message || err));
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
      window.LabBotToast.error("상세 정보를 불러오지 못했습니다: " + (err.message || err));
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
          window.LabBotToast.error("상태 변경에 실패했습니다: " + (err.message || err));
          btn.disabled = false;
        }
      });
    });
  }

  safetyStatusFilter.addEventListener("change", renderSafetyTable);

  // ---------- Robot Console (카메라 스냅샷 + 수동조작) ----------
  const robotCameraImg = document.getElementById("robotCameraImg");
  const robotCameraStatus = document.getElementById("robotCameraStatus");
  const robotModeBadge = document.getElementById("robotModeBadge");
  const robotAutoBtn = document.getElementById("robotAutoBtn");
  const driveButtons = document.querySelectorAll("[data-drive]");
  const joystickBase = document.getElementById("robotJoystickBase");
  const joystickKnob = document.getElementById("robotJoystickKnob");
  const joystickSpeedEl = document.getElementById("robotJoystickSpeed");
  const joystickTurnEl = document.getElementById("robotJoystickTurn");
  const camDpadButtons = document.querySelectorAll("[data-cam]");
  const camResetBtn = document.getElementById("robotCamResetBtn");
  const camPanValEl = document.getElementById("robotCamPanVal");
  const camTiltValEl = document.getElementById("robotCamTiltVal");

  const DRIVE_VALUES = {
    stop: { speed: 0, turn: 0 },
  };

  // 카메라 모드: "stream"(로컬 MJPEG 초고속 직결) | "snapshot"(Supabase 클라우드 스냅샷) | "offline"
  let robotCameraMode = "init";
  let robotCameraLastOkAt = null;
  let robotCurrentIp = null;
  let robotHealthCheckTick = 0;

  function showRobotCameraOffline(message) {
    robotCameraMode = "offline";
    robotCameraImg.style.display = "none";
    const lastText = robotCameraLastOkAt
      ? `마지막 수신: ${robotCameraLastOkAt.toLocaleTimeString("ko-KR")}`
      : "마지막 수신 기록 없음";
    robotCameraStatus.innerHTML = `
      <p class="robot-camera-message">${message}</p>
      <p class="robot-camera-meta mono">${lastText} · 시뮬레이션/실기기 연결 대기 중일 수 있습니다</p>
      <button type="button" class="btn btn-secondary btn-sm" id="robotCameraRetryBtn">다시 불러오기</button>
    `;
    const retryBtn = document.getElementById("robotCameraRetryBtn");
    if (retryBtn) {
      retryBtn.addEventListener("click", () => {
        robotCameraMode = "init";
        refreshRobotCamera();
      });
    }
  }

  let streamPumpRunning = false;
  let streamPumpCurrentIp = null;
  let activeBlobUrl = null;

  async function startZeroLagStream(localIp) {
    if (streamPumpRunning && streamPumpCurrentIp === localIp) return;
    streamPumpRunning = true;
    streamPumpCurrentIp = localIp;

    const targetUrl = `http://${localIp}:8080/snapshot`;
    let consecutiveErrors = 0;

    while (streamPumpRunning && streamPumpCurrentIp === localIp) {
      const startTime = performance.now();
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 1200);
        const resp = await fetch(`${targetUrl}?t=${Date.now()}`, {
          cache: "no-store",
          mode: "cors",
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (resp.ok) {
          consecutiveErrors = 0;
          const blob = await resp.blob();
          const newUrl = URL.createObjectURL(blob);
          const oldUrl = activeBlobUrl;
          activeBlobUrl = newUrl;
          robotCameraImg.src = newUrl;
          if (oldUrl) {
            requestAnimationFrame(() => URL.revokeObjectURL(oldUrl));
          }
          if (robotCameraMode !== "stream") {
            robotCameraMode = "stream";
            robotCameraImg.style.display = "block";
            robotCameraStatus.innerHTML = `
              <div style="margin-top: 6px;">
                <span class="badge badge-st-resolved" style="font-size: 11px;"><span class="badge-dot"></span>🟢 실시간 무지연 스트림 (${localIp}:8080 · 25 FPS)</span>
              </div>
            `;
          }
        } else {
          throw new Error("HTTP " + resp.status);
        }
      } catch (err) {
        consecutiveErrors++;
        if (consecutiveErrors > 4 && robotCameraMode !== "offline") {
          robotCameraMode = "offline";
          robotCameraStatus.innerHTML = `
            <div style="margin-top: 6px;">
              <span class="badge badge-st-closed" style="font-size: 11px;"><span class="badge-dot"></span>🔴 로봇 연결 대기 중 (${localIp})</span>
            </div>
          `;
        }
        await new Promise((r) => setTimeout(r, 150));
      }

      // 25 FPS 목표 안정적 페이싱 (지연 누적 0)
      const elapsed = performance.now() - startTime;
      const delay = Math.max(0, 38 - elapsed);
      if (delay > 0) {
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }

  async function refreshRobotCamera() {
    const localIp = (await window.LabBotRobotConsole.fetchRobotIp()) || "10.42.0.1";
    robotCurrentIp = localIp;
    startZeroLagStream(localIp);
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
        window.LabBotToast.error("원격조작 명령을 보내지 못했습니다: " + (err.message || err));
      }
    });
  });

  // 조이스틱: 원 안에서 드래그한 만큼 실시간으로 speed/turn을 보낸다(자동차 게임 방식).
  // 방향 버튼(한 번 클릭 -> 그 방향으로 계속 이동)이 답답하다는 피드백(2026-08-26)으로 교체.
  const JOY_SPEED_MAX = 70; // controller.py의 SPEED(70)와 동일 스케일
  const JOY_TURN_MAX = 90; // controller.py의 TURN_GAIN(90)과 동일 스케일
  const JOY_SEND_INTERVAL_MS = 50; // 로컬 직결 20Hz 초고속 반응 (0ms 지연)
  const JOY_KEEPALIVE_MS = 500; // 손을 안 움직여도 3초 dead-man switch보다 훨씬 짧게 계속 갱신

  let joyDragging = false;
  let joyRadius = 0;
  let joyLastSpeed = 0;
  let joyLastTurn = 0;
  let joyLastSentAt = 0;
  let joyKeepaliveTimer = null;

  function joySetKnob(dx, dy) {
    joystickKnob.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
  }

  async function joySendCommand(speed, turn) {
    try {
      await window.LabBotRobotConsole.setRobotCommand({ mode: "manual", speed, turn });
    } catch (err) {
      window.LabBotToast.error("원격조작 명령을 보내지 못했습니다: " + (err.message || err));
    }
  }

  function joyUpdateFromPointer(clientX, clientY) {
    const rect = joystickBase.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    let dx = clientX - cx;
    let dy = clientY - cy;
    const dist = Math.hypot(dx, dy);
    if (dist > joyRadius) {
      dx = (dx / dist) * joyRadius;
      dy = (dy / dist) * joyRadius;
    }
    joySetKnob(dx, dy);

    const speed = Math.round((-dy / joyRadius) * JOY_SPEED_MAX);
    const turn = Math.round((dx / joyRadius) * JOY_TURN_MAX);
    joyLastSpeed = speed;
    joyLastTurn = turn;
    joystickSpeedEl.textContent = speed;
    joystickTurnEl.textContent = turn;

    const now = Date.now();
    if (now - joyLastSentAt >= JOY_SEND_INTERVAL_MS) {
      joyLastSentAt = now;
      joySendCommand(speed, turn);
    }
  }

  function joyEnd() {
    if (!joyDragging) return;
    joyDragging = false;
    joystickBase.classList.remove("is-dragging");
    joySetKnob(0, 0);
    joyLastSpeed = 0;
    joyLastTurn = 0;
    joystickSpeedEl.textContent = "0";
    joystickTurnEl.textContent = "0";
    if (joyKeepaliveTimer) {
      clearInterval(joyKeepaliveTimer);
      joyKeepaliveTimer = null;
    }
    joySendCommand(0, 0); // 손을 떼면 그 자리에서 즉시 정지
    window.removeEventListener("pointermove", joyOnMove);
    window.removeEventListener("pointerup", joyEnd);
  }

  function joyOnMove(e) {
    if (!joyDragging) return;
    joyUpdateFromPointer(e.clientX, e.clientY);
  }

  joystickBase.addEventListener("pointerdown", (e) => {
    joyDragging = true;
    joystickBase.classList.add("is-dragging");
    const rect = joystickBase.getBoundingClientRect();
    joyRadius = rect.width / 2 - joystickKnob.offsetWidth / 2;
    joyUpdateFromPointer(e.clientX, e.clientY);
    joyKeepaliveTimer = setInterval(() => {
      // 드래그한 채로 손을 안 움직여도 dead-man switch(3초)에 안 걸리도록 주기적으로 재전송
      joySendCommand(joyLastSpeed, joyLastTurn);
    }, JOY_KEEPALIVE_MS);
    window.addEventListener("pointermove", joyOnMove);
    window.addEventListener("pointerup", joyEnd);
  });

  // 카메라 각도 십자패드: 누르고 있는 동안 그 방향으로 서보가 계속 움직이고, 손을 떼면
  // (조이스틱과 달리) 그 각도에서 그대로 멈춘다 — 카메라는 "중앙 복귀"가 기본값이 아니라
  // 사용자가 마지막으로 본 방향을 계속 보고 있는 게 자연스럽기 때문이다.
  const CAM_STEP_DEG = 4;
  const CAM_REPEAT_MS = 120;
  const CAM_ANGLE_MIN = 0;
  const CAM_ANGLE_MAX = 180;
  const CAM_ANGLE_CENTER = 90;

  let camPan = CAM_ANGLE_CENTER;
  let camTilt = CAM_ANGLE_CENTER;
  let camRepeatTimer = null;

  function camClamp(v) {
    return Math.max(CAM_ANGLE_MIN, Math.min(CAM_ANGLE_MAX, v));
  }

  function camRender() {
    camPanValEl.textContent = camPan;
    camTiltValEl.textContent = camTilt;
  }

  async function camSend() {
    try {
      await window.LabBotRobotConsole.setCameraAngle({ cam_pan: camPan, cam_tilt: camTilt });
    } catch (err) {
      window.LabBotToast.error("카메라 각도 명령을 보내지 못했습니다: " + (err.message || err));
    }
  }

  function camStep(direction) {
    if (direction === "up") camTilt = camClamp(camTilt - CAM_STEP_DEG);
    else if (direction === "down") camTilt = camClamp(camTilt + CAM_STEP_DEG);
    else if (direction === "left") camPan = camClamp(camPan - CAM_STEP_DEG);
    else if (direction === "right") camPan = camClamp(camPan + CAM_STEP_DEG);
    camRender();
    camSend();
  }

  function camStopRepeat() {
    if (camRepeatTimer) {
      clearInterval(camRepeatTimer);
      camRepeatTimer = null;
    }
    camDpadButtons.forEach((b) => b.classList.remove("is-active"));
    window.removeEventListener("pointerup", camStopRepeat);
  }

  camDpadButtons.forEach((btn) => {
    btn.addEventListener("pointerdown", () => {
      const direction = btn.dataset.cam;
      btn.classList.add("is-active");
      camStep(direction); // 누르자마자 한 번 즉시 반응
      camRepeatTimer = setInterval(() => camStep(direction), CAM_REPEAT_MS);
      window.addEventListener("pointerup", camStopRepeat);
    });
  });

  camResetBtn.addEventListener("click", () => {
    camPan = CAM_ANGLE_CENTER;
    camTilt = CAM_ANGLE_CENTER;
    camRender();
    camSend();
  });

  robotAutoBtn.addEventListener("click", async () => {
    try {
      await window.LabBotRobotConsole.setRobotCommand({ mode: "auto", speed: 0, turn: 0 });
      await refreshRobotModeBadge();
    } catch (err) {
      window.LabBotToast.error("자동 모드로 전환하지 못했습니다: " + (err.message || err));
    }
  });

  let robotConsoleStarted = false;
  function startRobotConsolePolling() {
    if (robotConsoleStarted) return; // showPanel()이 여러 번 불려도 인터벌이 중복 생기지 않게
    robotConsoleStarted = true;
    refreshRobotCamera();
    refreshRobotModeBadge();
    setInterval(refreshRobotCamera, 1000);
    setInterval(refreshRobotModeBadge, 1000);

    // 카메라 각도 초기값을 화면 기본값(90/90)이 아니라 실제 로봇 마지막 상태로 맞춘다.
    // cam_pan/cam_tilt 컬럼이 아직 없으면(마이그레이션 전) 여기만 실패하고 화면 기본값
    // 그대로 쓴다 — 모드 배지/카메라 스냅샷 등 나머지 폴링에는 영향 없음.
    window.LabBotRobotConsole.fetchCameraAngle()
      .then((cmd) => {
        if (typeof cmd.cam_pan === "number") camPan = cmd.cam_pan;
        if (typeof cmd.cam_tilt === "number") camTilt = cmd.cam_tilt;
        camRender();
      })
      .catch(() => {
        console.warn("LabBot: 카메라 초기 각도를 못 불러왔습니다(마이그레이션 미실행일 수 있음)");
      });
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
      window.LabBotToast.error("물품 목록을 불러오지 못했습니다: " + (err.message || err));
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
      window.LabBotToast.success("실사가 제출되었습니다.");
    } catch (err) {
      window.LabBotToast.error("실사 제출에 실패했습니다: " + (err.message || err));
    } finally {
      auditSubmitBtn.disabled = false;
    }
  });

  async function renderAuditSessions() {
    let sessions;
    try {
      sessions = await window.LabBotAudit.fetchAuditSessions();
    } catch (err) {
      window.LabBotToast.error("실사 이력을 불러오지 못했습니다: " + (err.message || err));
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
      window.LabBotToast.error("실사 상세를 불러오지 못했습니다: " + (err.message || err));
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

  // ---------- 문의 (사용자가 우하단 ✉️ 버튼으로 남긴 문의) ----------
  // 마이페이지의 "내 문의" 카드(.inquiry-card)와 같은 모양을 재사용하고, 관리자용으로
  // 답변 입력칸+등록 버튼만 카드 안에 그대로 붙여둔다 — 목록 따로/상세 패널 따로 열 필요
  // 없이, 카드 하나에서 바로 답변까지 끝낼 수 있게.
  function inquiryStatusBadge(status) {
    const { INQUIRY_STATUS_LABEL, INQUIRY_STATUS_BADGE_CLASS } = window.LabBotInquiry;
    const label = INQUIRY_STATUS_LABEL[status] || status;
    const cls = INQUIRY_STATUS_BADGE_CLASS[status] || "badge-inuse";
    return `<span class="badge ${cls}"><span class="badge-dot"></span>${label}</span>`;
  }

  function renderInquiryCard(q) {
    const { escapeHtml } = window.LabBotItems;

    const isClosed = q.status === "closed";
    const isAnswered = q.status === "answered";

    // 종결된 문의는 더 손댈 일이 없으니 답변을 읽기 전용으로만 보여준다. 그 외(open/answered)는
    // 답변 입력칸을 계속 열어두되, 이미 답변한 건은 실수로 조용히 덮어쓰지 않도록 등록 전 확인을
    // 받고 버튼 문구도 "수정"으로 구분한다. answered일 때 기존 답변을 textarea에 다시 채워
    // 보여주므로, 위에 별도로 또 표시하면 같은 내용이 중복되어 그때는 생략한다.
    const bodyHtml = isClosed
      ? `${q.admin_reply ? `<p class="inquiry-card-reply"><strong>답변</strong> · ${escapeHtml(q.admin_reply)}</p>` : ""}
         <p class="inquiry-card-closed-note">종결된 문의입니다.</p>`
      : `
        <textarea class="safety-note-input" placeholder="답변을 입력하세요" rows="2">${escapeHtml(q.admin_reply || "")}</textarea>
        <div class="safety-actions">
          <button type="button" class="btn btn-primary btn-sm" data-action="reply">${isAnswered ? "답변 수정" : "답변 등록"}</button>
          ${isAnswered ? `<button type="button" class="btn btn-secondary btn-sm" data-action="close-inquiry">종결</button>` : ""}
        </div>
      `;

    const card = document.createElement("article");
    card.className = "inquiry-card";
    card.innerHTML = `
      <div class="inquiry-card-header">
        ${inquiryStatusBadge(q.status)}
        <h3 class="inquiry-card-subject">${escapeHtml(q.subject)}</h3>
        <span class="inquiry-card-date">${escapeHtml((q.profiles && q.profiles.name) || "알 수 없음")} · ${new Date(q.created_at).toLocaleString("ko-KR")}</span>
      </div>
      <p class="inquiry-card-message">${escapeHtml(q.message)}</p>
      ${bodyHtml}
    `;

    const replyBtn = card.querySelector('[data-action="reply"]');
    if (replyBtn) {
      replyBtn.addEventListener("click", async (e) => {
        const reply = card.querySelector("textarea").value.trim();
        if (!reply) {
          window.LabBotToast.error("답변 내용을 입력해주세요.");
          return;
        }
        if (isAnswered && !confirm("이미 등록된 답변을 덮어씁니다. 계속할까요?")) return;

        const btn = e.currentTarget;
        const originalLabel = btn.textContent;
        btn.disabled = true;
        btn.textContent = "등록 중...";
        try {
          await window.LabBotInquiry.replyInquiry(q.id, reply);
          window.LabBotToast.success("답변을 등록했습니다.");
          await renderInquiryCards();
        } catch (err) {
          window.LabBotToast.error("답변 등록에 실패했습니다: " + (err.message || err));
          btn.disabled = false;
          btn.textContent = originalLabel;
        }
      });
    }

    const closeBtn = card.querySelector('[data-action="close-inquiry"]');
    if (closeBtn) {
      closeBtn.addEventListener("click", async (e) => {
        if (!confirm("이 문의를 종결할까요? 종결 후에는 답변을 다시 수정할 수 없습니다.")) return;
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await window.LabBotInquiry.closeInquiry(q.id);
          window.LabBotToast.success("문의를 종결했습니다.");
          await renderInquiryCards();
        } catch (err) {
          window.LabBotToast.error("종결 처리에 실패했습니다: " + (err.message || err));
          btn.disabled = false;
        }
      });
    }

    return card;
  }

  function renderInquiryPagination(totalCount) {
    const totalPages = Math.max(1, Math.ceil(totalCount / INQUIRY_PAGE_SIZE));
    if (inquiryPage > totalPages) inquiryPage = totalPages;

    if (totalPages <= 1) {
      inquiryPaginationEl.innerHTML = "";
      return;
    }

    const goTo = (page) => {
      inquiryPage = page;
      renderInquiryCards();
      inquiryListEl.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    inquiryPaginationEl.innerHTML = `
      <button type="button" class="btn btn-secondary btn-sm" data-page-action="prev" ${inquiryPage === 1 ? "disabled" : ""}>이전</button>
      <span class="pagination-status mono">${inquiryPage} / ${totalPages}</span>
      <button type="button" class="btn btn-secondary btn-sm" data-page-action="next" ${inquiryPage === totalPages ? "disabled" : ""}>다음</button>
    `;
    inquiryPaginationEl.querySelector('[data-page-action="prev"]').addEventListener("click", () => goTo(inquiryPage - 1));
    inquiryPaginationEl.querySelector('[data-page-action="next"]').addEventListener("click", () => goTo(inquiryPage + 1));
  }

  // 관리자가 마지막으로 본 문의 id(localStorage)보다 새로운 게 있으면 토스트로 알려준다.
  // 처음 켜보는 관리자 화면(저장된 값이 아예 없을 때)은 기존 문의 전체가 "새 문의"로
  // 오인되지 않게 조용히 기준점만 저장하고 넘어간다.
  function notifyNewInquiries(inquiries) {
    const KEY = "labbot_admin_seen_max_inquiry_id";
    const lastMaxId = Number(localStorage.getItem(KEY) || 0);
    const currentMaxId = inquiries.reduce((max, q) => Math.max(max, q.id), 0);

    if (lastMaxId > 0) {
      const newCount = inquiries.filter((q) => q.id > lastMaxId).length;
      if (newCount > 0) {
        window.LabBotToast.info(`새 문의가 ${newCount}건 접수되었습니다.`);
      }
    }

    if (currentMaxId > lastMaxId) {
      localStorage.setItem(KEY, String(currentMaxId));
    }
  }

  async function renderInquiryCards() {
    let inquiries;
    try {
      inquiries = await window.LabBotInquiry.fetchAllInquiries();
    } catch (err) {
      window.LabBotToast.error("문의 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    notifyNewInquiries(inquiries);

    inquiryEmptyState.style.display = inquiries.length === 0 ? "block" : "none";
    const start = (inquiryPage - 1) * INQUIRY_PAGE_SIZE;
    const pageInquiries = inquiries.slice(start, start + INQUIRY_PAGE_SIZE);
    inquiryListEl.innerHTML = "";
    pageInquiries.forEach((q) => inquiryListEl.appendChild(renderInquiryCard(q)));
    renderInquiryPagination(inquiries.length);
  }

  // ---------- 사용자 관리 (전체 사용자 + 대여/연체/파손신고 이력 + 경고) ----------
  let userSearchTerm = "";

  // "연체"는 loans 테이블에 별도 컬럼이 없다 — isOverdue()와 같은 기준(반납 안 됐고
  // due_at이 지났음)으로 매번 다시 계산한다(rentals.js의 연체 판단 로직을 그대로 재사용).
  function computeUserStats(userId, loans, damageReports) {
    const userLoans = loans.filter((l) => l.user_id === userId);
    // 예약중/취소됨은 실제로 받아가거나 쓴 게 아니라서 "대여 이력"에서 뺀다.
    const totalLoans = userLoans.filter((l) => l.status !== "예약중" && l.status !== "취소됨").length;
    const currentOverdue = userLoans.filter((l) => window.LabBotRentals.isOverdue(l)).length;
    const pastLateReturns = userLoans.filter(
      (l) => l.returned_at && l.due_at && new Date(l.returned_at) > new Date(l.due_at)
    ).length;
    const damageCount = damageReports.filter((r) => r.reported_by === userId).length;
    return { totalLoans, currentOverdue, pastLateReturns, damageCount };
  }

  function filterUsers(users) {
    const term = userSearchTerm.trim().toLowerCase();
    if (!term) return users;
    return users.filter(
      (u) => u.name.toLowerCase().includes(term) || (u.email || "").toLowerCase().includes(term)
    );
  }

  async function renderUserTable() {
    const { escapeHtml } = window.LabBotItems;

    let users, loans, damageReports, warningCounts;
    try {
      [users, loans, damageReports, warningCounts] = await Promise.all([
        window.LabBotUserAdmin.fetchAllUsers(),
        window.LabBotRentals.fetchAllLoans(),
        window.LabBotDamage.fetchAllDamageReports(),
        window.LabBotUserAdmin.fetchWarningCounts(),
      ]);
    } catch (err) {
      window.LabBotToast.error("사용자 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const filtered = filterUsers(users);

    if (filtered.length === 0) {
      userTableBody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">검색 결과가 없습니다.</td></tr>`;
      return;
    }

    userTableBody.innerHTML = "";
    filtered.forEach((u) => {
      const stats = computeUserStats(u.id, loans, damageReports);
      const warningCount = warningCounts[u.id] || 0;

      const row = document.createElement("tr");
      row.innerHTML = `
        <td data-label="이름">${escapeHtml(u.name)}</td>
        <td data-label="이메일" class="mono">${escapeHtml(u.email || "-")}</td>
        <td data-label="권한">${u.role === "admin" ? '<span class="badge badge-st-resolved"><span class="badge-dot"></span>관리자</span>' : "일반"}</td>
        <td data-label="가입일" class="mono">${new Date(u.created_at).toLocaleDateString("ko-KR")}</td>
        <td data-label="대여 이력">${stats.totalLoans}건</td>
        <td data-label="현재 연체">${
          stats.currentOverdue > 0
            ? `<span class="badge badge-sev-high"><span class="badge-dot"></span>${stats.currentOverdue}건</span>`
            : "-"
        }</td>
        <td data-label="연체 이력">${stats.pastLateReturns > 0 ? `${stats.pastLateReturns}건` : "-"}</td>
        <td data-label="파손 신고">${stats.damageCount > 0 ? `${stats.damageCount}건` : "-"}</td>
        <td data-label="경고">${
          warningCount > 0
            ? `<span class="badge badge-sev-medium"><span class="badge-dot"></span>${warningCount}회</span>`
            : "-"
        }</td>
        <td data-label="작업" class="stock-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="warn">경고 추가</button>
          <button type="button" class="btn btn-secondary btn-sm" data-action="history">이력</button>
        </td>
      `;

      row.querySelector('[data-action="warn"]').addEventListener("click", () => promptAddWarning(u));
      row.querySelector('[data-action="history"]').addEventListener("click", () => showUserWarningHistory(u));

      userTableBody.appendChild(row);
    });
  }

  let userSearchDebounceTimer = null;
  userSearchInput.addEventListener("input", () => {
    clearTimeout(userSearchDebounceTimer);
    userSearchDebounceTimer = setTimeout(() => {
      userSearchTerm = userSearchInput.value;
      renderUserTable();
    }, 300);
  });

  // 경고 사유를 고르게 하는 모달 — 재고 조정 사유 모달(promptStockAdjustmentReason)과
  // 같은 패턴: 선택지로 강제하고 "기타"일 때만 메모를 받는다.
  function promptAddWarning(user) {
    const { escapeHtml } = window.LabBotItems;
    const { WARNING_REASONS } = window.LabBotUserAdmin;

    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card">
        <h3 class="modal-title">경고 추가 — ${escapeHtml(user.name)}</h3>
        <div class="modal-field">
          <label>사유</label>
          <select id="warnReasonSelect" class="location-filter-select" style="width: 100%;">
            ${WARNING_REASONS.map((r) => `<option value="${r}">${r}</option>`).join("")}
          </select>
        </div>
        <div class="modal-field" id="warnNoteField" style="display: none;">
          <label>메모</label>
          <textarea id="warnNoteInput" placeholder="간단히 적어주세요"></textarea>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="cancel">취소</button>
          <button type="button" class="btn btn-primary btn-sm" data-action="confirm">경고 등록</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const reasonSelect = overlay.querySelector("#warnReasonSelect");
    const noteField = overlay.querySelector("#warnNoteField");
    const noteInput = overlay.querySelector("#warnNoteInput");

    reasonSelect.addEventListener("change", () => {
      noteField.style.display = reasonSelect.value === "기타" ? "block" : "none";
    });

    const close = () => overlay.remove();
    overlay.querySelector('[data-action="cancel"]').addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
    overlay.querySelector('[data-action="confirm"]').addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const session = await window.LabBotAuth.getSession();
        await window.LabBotUserAdmin.addUserWarning(user.id, {
          reason: reasonSelect.value,
          note: noteInput.value.trim(),
          createdBy: session && session.id,
        });
        window.LabBotToast.success(`"${user.name}"에게 경고를 추가했습니다.`);
        close();
        await renderUserTable();
      } catch (err) {
        window.LabBotToast.error("경고 추가에 실패했습니다: " + (err.message || err));
        btn.disabled = false;
      }
    });
  }

  // 경고 이력 모달 — 재고 조정 이력 모달(showStockHistory)과 같은 패턴. 잘못 남긴 경고는
  // 여기서 바로 삭제할 수 있다(관리자 내부 메모라 되돌릴 방법이 있어야 한다).
  async function showUserWarningHistory(user) {
    const { escapeHtml } = window.LabBotItems;

    let warnings;
    try {
      warnings = await window.LabBotUserAdmin.fetchUserWarnings(user.id);
    } catch (err) {
      window.LabBotToast.error("경고 이력을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card">
        <h3 class="modal-title">경고 이력 — ${escapeHtml(user.name)}</h3>
        <ul class="safety-log-list" id="warnHistoryList">
          ${
            warnings.length === 0
              ? "<li>아직 경고 이력이 없습니다.</li>"
              : warnings
                  .map(
                    (w) => `
                <li data-warning-id="${w.id}">
                  [${new Date(w.created_at).toLocaleString("ko-KR")}] ${escapeHtml((w.creator && w.creator.name) || "관리자")} — ${escapeHtml(w.reason)}
                  ${w.note ? `(${escapeHtml(w.note)})` : ""}
                  <button type="button" class="link-btn" data-action="delete-warning" data-warning-id="${w.id}">삭제</button>
                </li>
              `
                  )
                  .join("")
          }
        </ul>
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="close">닫기</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.querySelector('[data-action="close"]').addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
    overlay.querySelectorAll('[data-action="delete-warning"]').forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("이 경고를 삭제할까요?")) return;
        try {
          await window.LabBotUserAdmin.deleteUserWarning(Number(btn.dataset.warningId));
          close();
          await renderUserTable();
        } catch (err) {
          window.LabBotToast.error("경고 삭제에 실패했습니다: " + (err.message || err));
        }
      });
    });
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
      window.LabBotToast.error("모든 항목을 올바르게 입력해주세요.");
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
      window.LabBotToast.error("물품 등록에 실패했습니다: " + (err.message || err));
    } finally {
      submitBtn.disabled = false;
    }
  });

  function switchTab(target) {
    tabButtons.forEach((b) => b.classList.remove("active"));
    tabPanels.forEach((p) => p.classList.remove("active"));

    document.querySelector(`.tab-btn[data-tab="${target}"]`).classList.add("active");
    document.getElementById(`tab-${target}`).classList.add("active");
  }

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.querySelectorAll("[data-goto-tab]").forEach((card) => {
    card.addEventListener("click", () => switchTab(card.dataset.gotoTab));
  });


  // 요약 카드 — 탭마다 이미 fetch하는 데이터를 여기서 다시 세는 대신, 굳이 캐시를 만들지
  // 않고 그냥 한 번씩 더 불러온다(관리자 화면 데이터량이 적어서 성능에 영향 없음).
  async function renderSummaryCards() {
    try {
      const [items, loans, damageReports, safetyEvents, inquiries] = await Promise.all([
        window.LabBotItems.searchItems({}),
        window.LabBotRentals.fetchAllLoans(),
        window.LabBotDamage.fetchAllDamageReports(),
        window.LabBotSafety.fetchSafetyEvents({}),
        window.LabBotInquiry.fetchAllInquiries(),
      ]);

      // 사용자별로 하나라도 연체중인 대여가 있으면 그 사용자를 "연체중"으로 센다
      // (건수가 아니라 사람 수 — 요약 카드는 "지금 챙겨야 할 사람이 몇 명인지"가 중요하다).
      const overdueUserIds = new Set(
        loans.filter((l) => window.LabBotRentals.isOverdue(l)).map((l) => l.user_id)
      );

      const { computeStockStatus } = window.LabBotItems;
      const lowStockCount = items.filter((it) => {
        const status = computeStockStatus(it);
        return status === "LOW_STOCK" || status === "OUT_OF_STOCK";
      }).length;

      document.getElementById("summaryTotalItems").textContent = items.length;
      document.getElementById("summaryLowStock").textContent = lowStockCount;
      document.getElementById("summaryActiveLoans").textContent = loans.filter((l) => l.status === "대여중").length;
      document.getElementById("summaryPendingDamage").textContent = damageReports.filter(
        (r) => r.status !== "analyzed"
      ).length;
      document.getElementById("summaryNeedsReview").textContent = safetyEvents.filter(
        (e) => e.status === "NEEDS_REVIEW"
      ).length;
      document.getElementById("summaryPendingInquiry").textContent = inquiries.filter(
        (q) => q.status === "open"
      ).length;
      document.getElementById("summaryOverdueUsers").textContent = overdueUserIds.size;
    } catch (err) {
      console.warn("LabBot: 관리자 요약 카드를 불러오지 못했습니다", err);
    }
  }

  async function showPanel() {
    forbidden.style.display = "none";
    panel.style.display = "block";
    renderCategoryOptions();
    renderLocationOptions();
    await renderStockTable();
    await renderHistoryTable();
    await renderDamageTable();
    await renderSafetyTable();
    await renderAuditChecklist();
    await renderAuditSessions();
    await renderInquiryCards();
    await renderUserTable();
    await renderSummaryCards();
    // startRobotConsolePolling() 호출이 빠져 있어서 로봇 카메라/모드 배지가 아예 갱신되지
    // 않고 있었다(이미지 태그가 항상 빈 채로 남는 문제 — GPT 리뷰 지적의 실제 원인).
    startRobotConsolePolling();
  }

  function showForbidden() {
    forbidden.style.display = "block";
    panel.style.display = "none";
  }

  // 로그아웃 버튼은 상단 네비게이션(nav.js)에 있는 것 하나만 쓴다 — 예전엔 이 페이지 안에도
  // 똑같은 기능의 버튼이 따로 있어서 중복으로 보였다(GPT 리뷰 지적).

  // 로그인은 login.html 한 곳에서만 한다 — 비로그인 상태면 requireLogin이
  // login.html?redirect=admin.html로 보내고, 로그인에 성공하면 다시 이 페이지로
  // 돌아온다(auth.js REDIRECT_ALLOWLIST에 admin.html이 이미 등록되어 있음).
  const session = await window.LabBotAuth.requireLogin("admin.html");
  if (!session) return;

  if (session.role !== "admin") {
    showForbidden();
    return;
  }

  await showPanel();
});
