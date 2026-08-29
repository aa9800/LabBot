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
      const rawEvents = await window.LabBotSafety.fetchSafetyEvents({
        status: safetyStatusFilter.value,
        limit: 200,
      });
      events = window.LabBotSafety
        .collapseRepeatedSafetyEvents(rawEvents)
        .filter(window.LabBotSafety.isActionableSafetyEvent);
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
      const ruleLabel = window.LabBotSafety.getSafetyRuleLabel(ev.rule_id);
      const repeatedBadge =
        ev.repeat_count > 1
          ? `<span class="safety-repeat-badge" title="같은 위험이 ${ev.repeat_count}회 연속 감지되어 한 건으로 묶였습니다.">반복 ${ev.repeat_count}회</span>`
          : "";
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>
          <div class="safety-rule-cell">
            <span>${window.LabBotItems.escapeHtml(ruleLabel)}</span>
            <span class="mono safety-rule-code">${window.LabBotItems.escapeHtml(ev.rule_id)}</span>
            ${repeatedBadge}
          </div>
        </td>
        <td>${severityBadge(ev.severity)}</td>
        <td>${statusBadge(ev.status)}</td>
        <td>${window.LabBotItems.escapeHtml(ev.source)}</td>
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
    const ruleLabel = window.LabBotSafety.getSafetyRuleLabel(event.rule_id);
    const cleanNote = window.LabBotSafety.cleanSafetyNote(event.note);
    const evidencePath = window.LabBotSafety.extractSafetyEvidencePath(event);
    let evidenceUrl = null;
    let evidenceLoadFailed = false;
    if (evidencePath) {
      try {
        evidenceUrl = await window.LabBotSafety.getSafetyEvidenceUrl(event);
      } catch (err) {
        evidenceLoadFailed = true;
        console.warn("LabBot: 안전 이벤트 증거 사진을 불러오지 못했습니다", err);
      }
    }

    safetyDetail.style.display = "block";
    safetyDetail.innerHTML = `
      <div class="safety-detail-row"><span class="label">감지 항목</span><span>${window.LabBotItems.escapeHtml(ruleLabel)} <span class="mono safety-rule-code">${window.LabBotItems.escapeHtml(event.rule_id)}</span></span></div>
      <div class="safety-detail-row"><span class="label">심각도</span>${severityBadge(event.severity)}</div>
      <div class="safety-detail-row"><span class="label">상태</span>${statusBadge(event.status)}</div>
      <div class="safety-detail-row"><span class="label">출처</span><span>${window.LabBotItems.escapeHtml(event.source)}</span></div>
      <div class="safety-detail-row"><span class="label">감지시각</span><span class="mono">${new Date(event.detected_at).toLocaleString("ko-KR")}</span></div>
      <div class="safety-detail-row"><span class="label">감지 메모</span><span>${window.LabBotItems.escapeHtml(cleanNote) || "-"}</span></div>
      ${event.resolved_at ? `<div class="safety-detail-row"><span class="label">조치 메모</span><span>${window.LabBotItems.escapeHtml(event.resolution_note) || "-"}</span></div>` : ""}

      ${evidencePath ? `<div class="safety-evidence" id="safetyEvidenceSlot" aria-live="polite"></div>` : ""}

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

    const evidenceSlot = safetyDetail.querySelector("#safetyEvidenceSlot");
    if (evidenceSlot) {
      const evidenceTitle = document.createElement("p");
      evidenceTitle.className = "safety-evidence-title";
      evidenceTitle.textContent = "감지 당시 현장 사진";
      evidenceSlot.appendChild(evidenceTitle);

      if (evidenceUrl) {
        const image = document.createElement("img");
        image.className = "safety-evidence-image";
        image.src = evidenceUrl;
        image.alt = `${ruleLabel} 감지 당시 로봇 카메라 사진`;
        image.loading = "lazy";
        evidenceSlot.appendChild(image);
      } else {
        const message = document.createElement("p");
        message.className = "safety-evidence-unavailable";
        message.textContent = evidenceLoadFailed
          ? "사진 파일을 불러오지 못했습니다. 저장소 연결 상태를 확인해 주세요."
          : "사진 파일 주소를 확인할 수 없습니다.";
        evidenceSlot.appendChild(message);
      }
    }

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
  const keyboardFeedbackEl = document.getElementById("robotKeyboardFeedback");
  const keyboardStatusEl = document.getElementById("robotKeyboardStatus");
  const keyboardKeyEls = document.querySelectorAll("[data-control-key]");
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

  const targetRealBtn = document.getElementById("targetRealBtn");
  const targetSimBtn = document.getElementById("targetSimBtn");

  function updateTargetSwitcherUI(mode) {
    if (!targetRealBtn || !targetSimBtn) return;
    if (mode === "sim") {
      targetSimBtn.classList.add("active");
      targetSimBtn.style.opacity = "1";
      targetRealBtn.classList.remove("active");
      targetRealBtn.style.opacity = "0.6";
    } else {
      targetRealBtn.classList.add("active");
      targetRealBtn.style.opacity = "1";
      targetSimBtn.classList.remove("active");
      targetSimBtn.style.opacity = "0.6";
    }
  }

  if (targetRealBtn && targetSimBtn) {
    const initialMode = window.LabBotRobotConsole.getTargetMode ? window.LabBotRobotConsole.getTargetMode() : "real";
    updateTargetSwitcherUI(initialMode);

    targetRealBtn.addEventListener("click", async () => {
      await window.LabBotRobotConsole.setTargetMode("real");
      updateTargetSwitcherUI("real");
      robotCameraMode = "init";
      refreshRobotCamera();
      window.LabBotToast.success("🤖 관제 대상: 실물 로봇 (Raspbot · 10.42.0.1) 전환");
    });

    targetSimBtn.addEventListener("click", async () => {
      await window.LabBotRobotConsole.setTargetMode("sim");
      updateTargetSwitcherUI("sim");
      robotCameraMode = "init";
      refreshRobotCamera();
      window.LabBotToast.info("🌐 관제 대상: 가상 디지털 트윈 (Isaac Sim · localhost) 전환");
    });
  }

  async function refreshRobotCamera() {
    const localIp = await window.LabBotRobotConsole.fetchRobotIp();
    const mode = window.LabBotRobotConsole.getTargetMode ? window.LabBotRobotConsole.getTargetMode() : "real";
    const modeLabel = mode === "sim" ? "🌐 Isaac Sim 가상 트윈" : "🤖 Raspbot 실물 로봇";
    robotCurrentIp = localIp;
    const streamUrl = `http://${localIp}:8080/stream`;

    robotCameraImg.onerror = () => {
      robotCameraMode = "offline";
      robotCameraStatus.innerHTML = `
        <div style="margin-top: 6px;">
          <span class="badge badge-st-closed" style="font-size: 11px;"><span class="badge-dot"></span>🔴 ${modeLabel} 연결 대기 중 (${localIp}:8080)</span>
        </div>
      `;
      setTimeout(() => {
        if (robotCameraMode === "offline") {
          robotCameraImg.src = streamUrl;
        }
      }, 2000);
    };

    // 초록 배지는 첫 프레임이 실제로 도착한 뒤에만 켠다. 예전에는 src를 대입하자마자
    // "🟢 실시간 스트림"을 칠해서, 로봇이 꺼져 있어도 잠시 초록불이 떴고
    // 반대로 한 번 끊겼다 복구되면 onload가 없어서 영영 빨간불로 남아 있었다.
    robotCameraImg.onload = () => {
      robotCameraMode = "stream";
      if (robotHudOverlay) robotHudOverlay.style.display = "flex";
      robotCameraStatus.innerHTML = `
        <div style="margin-top: 6px;">
          <span class="badge badge-st-resolved" style="font-size: 11px;"><span class="badge-dot"></span>🟢 ${modeLabel} 실시간 스트림 (${localIp}:8080)</span>
        </div>
      `;
    };

    robotCameraMode = "connecting";
    robotCameraStatus.innerHTML = `
      <div style="margin-top: 6px;">
        <span class="badge" style="font-size: 11px;"><span class="badge-dot"></span>⏳ ${modeLabel} 연결 중… (${localIp}:8080)</span>
      </div>
    `;
    robotCameraImg.src = streamUrl;
    robotCameraImg.style.display = "block";
  }


  async function refreshRobotModeBadge() {
    try {
      // 1. 로컬 실시간 텔레메트리 최우선 반영
      const telemetry = await window.LabBotRobotConsole.fetchTelemetry(600);
      if (telemetry && telemetry.mode) {
        const isManual = telemetry.mode === "manual";
        robotModeBadge.className = `badge ${isManual ? "badge-st-in_progress" : "badge-st-resolved"}`;
        robotModeBadge.innerHTML = `<span class="badge-dot"></span>${isManual ? "수동조작 중" : "자동순찰 중"}`;
        return;
      }
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
        if (btn.dataset.drive === "stop") {
          activeKeyboardKeys.clear();
          joyDragging = false;
          joystickBase.classList.remove("is-dragging");
          joySetKnob(0, 0);
          joyEmergencyStop();
          showTemporaryKeyboardFeedback("정지 버튼 입력됨", "stop");
        } else {
          await window.LabBotRobotConsole.setRobotCommand({ mode: "manual", ...values });
        }
        await refreshRobotModeBadge();
      } catch (err) {
        window.LabBotToast.error("원격조작 명령을 보내지 못했습니다: " + (err.message || err));
      }
    });
  });

  const robotScanQrBtn = document.getElementById("robotScanQrBtn");
  const robotScanQrResult = document.getElementById("robotScanQrResult");

  const scannedItemCard = document.getElementById("scannedItemCard");

  if (robotScanQrBtn) {
    robotScanQrBtn.addEventListener("click", async () => {
      robotScanQrBtn.disabled = true;
      robotScanQrBtn.innerHTML = `⌛ 물품 QR 인식 중...`;
      if (robotScanQrResult) robotScanQrResult.innerHTML = ``;
      if (scannedItemCard) scannedItemCard.style.display = "none";
      if (robotHudOverlay) {
        robotHudOverlay.style.boxShadow = "inset 0 0 24px rgba(37, 99, 235, 0.7)";
      }

      try {
        const localIp = robotCurrentIp || "10.42.0.1";
        const result = await window.LabBotRobotConsole.triggerQrScan(localIp);
        if (result && result.found) {
          const rawCode = String(result.code).trim();

          // Supabase items 테이블에서 물품 매칭
          const allItems = await window.LabBotItems.searchItems({});
          const matchedItem = allItems.find(
            (it) =>
              String(it.id) === rawCode ||
              (it.qr_code && it.qr_code.toLowerCase() === rawCode.toLowerCase()) ||
              it.name.toLowerCase().includes(rawCode.toLowerCase()) ||
              it.location.toLowerCase() === rawCode.toLowerCase()
          );

          if (robotHudOverlay) {
            robotHudOverlay.style.boxShadow = "inset 0 0 30px rgba(34, 197, 94, 0.8)";
            setTimeout(() => { if (robotHudOverlay) robotHudOverlay.style.boxShadow = "none"; }, 1500);
          }

          if (matchedItem) {
            const stockStatus = window.LabBotItems.computeStockStatus(matchedItem);
            const statusLabel = window.LabBotItems.STOCK_STATUS_LABEL[stockStatus] || "정상";
            const badgeCls = window.LabBotItems.STOCK_STATUS_BADGE_CLASS[stockStatus] || "badge-available";
            const iconSvg = window.LabBotItems.categoryIconOf(matchedItem.category);

            window.LabBotToast.success(`✅ 물품 인식 완료: [${matchedItem.name}] (${matchedItem.location})`);

            if (hudSafetyBadge) {
              hudSafetyBadge.className = "hud-tag hud-status-ok";
              hudSafetyBadge.innerHTML = `📦 ${matchedItem.name}`;
              setTimeout(() => {
                if (hudSafetyBadge) {
                  hudSafetyBadge.className = "hud-tag hud-status-ok";
                  hudSafetyBadge.innerHTML = "🟢 정상 주행";
                }
              }, 4000);
            }

            if (robotScanQrResult) {
              robotScanQrResult.innerHTML = `
                <span class="badge badge-st-resolved" style="font-size: 11px;">
                  <span class="badge-dot"></span>물품 확인: <strong>${matchedItem.name}</strong>
                </span>
              `;
            }

            if (scannedItemCard) {
              scannedItemCard.style.display = "block";
              scannedItemCard.innerHTML = `
                <div class="card" style="background: var(--surface); border: 1px solid var(--accent-border); border-radius: 8px; padding: 14px 18px; box-shadow: var(--shadow);">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <span style="display: inline-flex; width: 22px; height: 22px; color: var(--accent);">${iconSvg}</span>
                      <h4 style="margin: 0; font-size: 16px; color: var(--text);">${matchedItem.name}</h4>
                      <span class="badge ${badgeCls}">${statusLabel}</span>
                    </div>
                    <button type="button" class="btn btn-secondary btn-sm" id="closeScannedItemCardBtn" style="padding: 2px 6px; font-size: 11px;">✕ 닫기</button>
                  </div>
                  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
                    <div>📍 <strong>보관 위치:</strong> ${matchedItem.location}</div>
                    <div>📦 <strong>가용 재고:</strong> <span class="mono" style="font-weight: 600; color: var(--text);">${matchedItem.available_qty}</span> / ${matchedItem.total_qty} ${matchedItem.unit || "개"}</div>
                    <div>🏷️ <strong>분류:</strong> ${matchedItem.category}</div>
                    ${matchedItem.storage_condition ? `<div>❄️ <strong>보관:</strong> ${matchedItem.storage_condition}</div>` : ""}
                    ${matchedItem.expires_at ? `<div>📅 <strong>유효기간:</strong> ${matchedItem.expires_at}</div>` : ""}
                  </div>
                  <div style="display: flex; gap: 8px; justify-content: flex-end; align-items: center;">
                    <button type="button" class="btn btn-secondary btn-sm" id="scannedItemAuditConfirmBtn">✅ 재고 실사 확정</button>
                    <button type="button" class="btn btn-primary btn-sm" id="scannedItemViewStockBtn"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8" /><path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>재고표에서 보기</button>
                  </div>
                </div>
              `;

              document.getElementById("closeScannedItemCardBtn")?.addEventListener("click", () => {
                scannedItemCard.style.display = "none";
              });

              // 이 버튼은 예전에 성공 토스트만 띄우고 DB에는 아무것도 쓰지 않았다.
              // 관리자가 30개를 스캔하고 확정을 눌러도 audit_sessions는 비어 있었고,
              // 다음 실사에서 전부 미확인으로 떴다. "어느 실사 세션에 속하는 스캔인지"를
              // 정하는 설계가 아직 없어서, 거짓 성공을 없애는 쪽을 택한다 —
              // 실제 실사는 아래 [재고 실사] 탭의 체크리스트로 하도록 안내한다.
              document.getElementById("scannedItemAuditConfirmBtn")?.addEventListener("click", () => {
                window.LabBotToast.info(
                  `[${matchedItem.name}] 확인됨. 실사 기록은 [재고 실사] 탭에서 제출해주세요.`
                );
                scannedItemCard.style.display = "none";
                document.querySelector('[data-tab="audit"]')?.click();
              });

              document.getElementById("scannedItemViewStockBtn")?.addEventListener("click", () => {
                document.querySelector('[data-tab="stock"]')?.click();
                if (stockSearchInput) {
                  stockSearchInput.value = matchedItem.name;
                  stockSearchInput.dispatchEvent(new Event("input"));
                }
              });
            }
          } else {
            window.LabBotToast.success(`✅ QR 인식 성공: [${rawCode}]`);
            if (robotScanQrResult) {
              robotScanQrResult.innerHTML = `
                <span class="badge badge-st-resolved" style="font-size: 11px;">
                  <span class="badge-dot"></span>인식 코드: <strong>${rawCode}</strong>
                </span>
              `;
            }
          }
        } else {
          window.LabBotToast.error(result.message || "물품 QR 코드가 감지되지 않았습니다. 카메라 각도를 조절해 주세요.");
          if (robotHudOverlay) {
            robotHudOverlay.style.boxShadow = "inset 0 0 20px rgba(245, 158, 11, 0.6)";
            setTimeout(() => { if (robotHudOverlay) robotHudOverlay.style.boxShadow = "none"; }, 1000);
          }
          if (robotScanQrResult) {
            robotScanQrResult.innerHTML = `
              <span class="badge badge-st-in_progress" style="font-size: 11px;">
                <span class="badge-dot"></span>⚠️ QR 미감지 (각도 확인)
              </span>
            `;
          }
        }
      } catch (err) {
        window.LabBotToast.error("물품 QR 스캔 실패: " + (err.message || err));
        if (robotHudOverlay) robotHudOverlay.style.boxShadow = "none";
      } finally {
        robotScanQrBtn.disabled = false;
        robotScanQrBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8" /><path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg> 물품 QR 인식하기`;
      }
    });
  }

  // AI 비전 가드 모드 토글 (YOLOv11 실시간 탐지 스트림)
  let aiVisionActive = false;
  const robotAiVisionBtn = document.getElementById("robotAiVisionBtn");
  if (robotAiVisionBtn) {
    robotAiVisionBtn.addEventListener("click", () => {
      aiVisionActive = !aiVisionActive;
      const localIp = robotCurrentIp || "127.0.0.1";
      if (aiVisionActive) {
        robotAiVisionBtn.classList.add("btn-toggle-active");
        robotAiVisionBtn.textContent = "AI 비전 감지 중";
        robotCameraImg.src = window.LabBotRobotConsole.getAiVisionStreamUrl(localIp, 8080);
        window.LabBotToast.success("AI 실시간 비전 감지 모드가 켜졌습니다.");
      } else {
        robotAiVisionBtn.classList.remove("btn-toggle-active");
        robotAiVisionBtn.textContent = "AI 비전 감지";
        robotCameraImg.src = window.LabBotRobotConsole.getDirectStreamUrl(localIp, 8080);
        window.LabBotToast.info("기본 카메라 모드로 전환되었습니다.");
      }
    });
  }

  // AI 비전 모드일 때 로봇이 "지금 무엇을 보고 있는지"를 HUD에 띄운다.
  // /ai/stream이 그려주는 박스만으로는 클래스명·신뢰도를 읽기 어려워서,
  // /ai/status의 탐지 목록을 함께 읽어 요약해 보여준다.
  const hudAiBadge = document.getElementById("hudAiBadge");

  async function updateAiDetectionBadge() {
    if (!hudAiBadge) return;
    if (!aiVisionActive) {
      hudAiBadge.style.display = "none";
      return;
    }
    hudAiBadge.style.display = "";

    const status = await window.LabBotRobotConsole.fetchAiStatus();
    if (!status) {
      // 로봇이 응답하지 않으면 마지막 값을 그대로 두지 않는다 — 죽은 값을
      // 계속 보여주면 탐지가 되고 있는 것으로 오인한다.
      hudAiBadge.textContent = "🧠 AI 응답 없음";
      hudAiBadge.className = "hud-tag hud-ai-tag";
      return;
    }
    if (status.running === false) {
      hudAiBadge.textContent = "🧠 AI 정지됨";
      hudAiBadge.className = "hud-tag hud-ai-tag";
      return;
    }

    const dets = Array.isArray(status.detections) ? status.detections : [];
    const fps = status.actual_fps != null ? `${status.actual_fps}fps` : "";
    if (dets.length === 0) {
      hudAiBadge.textContent = `🧠 탐지 없음 · ${fps}`;
      hudAiBadge.className = "hud-tag hud-ai-tag";
      return;
    }

    // 같은 클래스가 여러 개면 개수로 묶고, 신뢰도가 높은 순으로 최대 3종만 보여준다.
    const byClass = new Map();
    dets.forEach((d) => {
      const key = d.class_name || "?";
      const prev = byClass.get(key) || { count: 0, conf: 0 };
      byClass.set(key, { count: prev.count + 1, conf: Math.max(prev.conf, d.confidence || 0) });
    });
    const summary = [...byClass.entries()]
      .sort((a, b) => b[1].conf - a[1].conf)
      .slice(0, 3)
      .map(([name, v]) => `${name}${v.count > 1 ? `×${v.count}` : ""} ${Math.round(v.conf * 100)}%`)
      .join(" · ");

    hudAiBadge.textContent = `🧠 ${summary} · ${fps}`;
    hudAiBadge.className = "hud-tag hud-ai-tag hud-ai-active";
  }
  setInterval(updateAiDetectionBadge, 1000);

  // 야간 경비 정책: 정기순찰 ↔ 센서대기 ↔ 이상 재확인 ↔ 조사 주행
  let latestNightGuardStatus = null;
  const robotIntruderGuardBtn = document.getElementById("robotIntruderGuardBtn");
  const nightPatrolInterval = document.getElementById("nightPatrolInterval");
  const nightGuardNextPatrol = document.getElementById("nightGuardNextPatrol");
  const aiGuardStatusBadge = document.getElementById("aiGuardStatusBadge");
  const aiLiveDetectionsList = document.getElementById("aiLiveDetectionsList");
  const aiGuardActionText = document.getElementById("aiGuardActionText");

  function renderNightGuardStatus(guard) {
    if (!guard) return;
    latestNightGuardStatus = guard;
    const active = !!guard.active;
    const enabled = !!guard.enabled;
    const investigating = guard.state === "investigating";
    if (nightPatrolInterval && document.activeElement !== nightPatrolInterval) {
      nightPatrolInterval.value = String(guard.patrol_interval_minutes || 30);
    }
    if (robotIntruderGuardBtn) {
      robotIntruderGuardBtn.classList.toggle("btn-toggle-active", enabled && !investigating);
      robotIntruderGuardBtn.classList.toggle("btn-toggle-danger-active", investigating);
      robotIntruderGuardBtn.textContent = enabled ? "🌙 자동 야간 경비 켜짐" : "🌙 자동 야간 경비 꺼짐";
    }
    if (aiGuardStatusBadge) {
      aiGuardStatusBadge.className = `badge ${investigating ? "badge-st-closed" : active ? "badge-st-resolved" : enabled ? "badge-st-in_progress" : "badge-st-open"}`;
      aiGuardStatusBadge.innerHTML = `<span class="badge-dot"></span>${guard.label || "상태 확인"}`;
    }
    if (aiGuardActionText) {
      aiGuardActionText.textContent = guard.reason ? `${guard.label} · ${guard.reason}` : (guard.label || "대기 중");
      aiGuardActionText.style.color = investigating ? "var(--danger)" : "var(--text-muted)";
    }
    if (nightGuardNextPatrol) {
      const remain = guard.next_patrol_in_seconds;
      nightGuardNextPatrol.textContent = active && Number.isFinite(remain)
        ? `다음 순찰 ${Math.ceil(remain / 60)}분 후`
        : enabled ? `${String(guard.start_hour).padStart(2, "0")}:00 자동 시작` : "";
    }
  }

  if (robotIntruderGuardBtn) {
    robotIntruderGuardBtn.addEventListener("click", async () => {
      const localIp = robotCurrentIp || "127.0.0.1";
      try {
        const enabled = !(latestNightGuardStatus?.enabled ?? true);
        const res = await window.LabBotRobotConsole.configureNightGuard({
          enabled: enabled ? 1 : 0,
          patrol_interval_minutes: Number(nightPatrolInterval?.value || 30),
        }, localIp);
        renderNightGuardStatus(res);
        window.LabBotToast[enabled ? "success" : "info"](
          enabled
            ? "자동 야간 경비를 켰습니다. 밤에는 정기순찰 사이 센서 대기로 전환됩니다."
            : "자동 야간 경비를 껐습니다. 기존 주간 대여 보조 운행은 유지됩니다."
        );
      } catch (err) {
        window.LabBotToast.error("야간 경비 설정 실패: " + (err.message || err));
      }
    });
  }

  if (nightPatrolInterval) {
    nightPatrolInterval.addEventListener("change", async () => {
      try {
        const res = await window.LabBotRobotConsole.configureNightGuard({
          enabled: latestNightGuardStatus?.enabled === false ? 0 : 1,
          patrol_interval_minutes: Number(nightPatrolInterval.value),
        }, robotCurrentIp || "127.0.0.1");
        renderNightGuardStatus(res);
        window.LabBotToast.success(`야간 순찰 간격을 ${nightPatrolInterval.value}분으로 변경했습니다.`);
      } catch (err) {
        window.LabBotToast.error("순찰 간격 변경 실패: " + (err.message || err));
      }
    });
  }

  // 원격 부저 경보 트리거 버튼
  const btnTriggerBuzzer = document.getElementById("btnTriggerBuzzer");
  if (btnTriggerBuzzer) {
    btnTriggerBuzzer.addEventListener("click", async () => {
      const localIp = robotCurrentIp || "127.0.0.1";
      try {
        const res = await window.LabBotRobotConsole.triggerRemoteBuzzer(localIp);
        window.LabBotToast.success(res.message || "로봇 부저 경보가 울렸습니다.");
      } catch (err) {
        window.LabBotToast.error("부저 호출 실패: " + (err.message || err));
      }
    });
  }

  // 실시간 AI 탐지 현황 & 방범 텔레메트리 업데이트 루프 (1.5초 주기)
  async function updateAiGuardTelemetry() {
    try {
      const localIp = robotCurrentIp || "127.0.0.1";
      const status = await window.LabBotRobotConsole.fetchAiStatus(localIp);
      if (status && status.status === "ok") {
        if (aiGuardActionText && status.guard_action && status.guard_action.includes("TRACKING")) {
          aiGuardActionText.textContent = status.guard_action || "대기 중";
          aiGuardActionText.style.color = "var(--danger)";
        } else if (latestNightGuardStatus) {
          renderNightGuardStatus(latestNightGuardStatus);
        }

        if (aiLiveDetectionsList) {
          if (status.detections && status.detections.length > 0) {
            aiLiveDetectionsList.innerHTML = status.detections
              .map((d) => {
                const isSafety = d.type === "SAFETY";
                return `<span class="badge ${isSafety ? "badge-st-closed" : "badge-st-resolved"}">
                  <span class="badge-dot"></span>${d.name_kr} (${d.confidence}%)
                </span>`;
              })
              .join("");
          } else {
            aiLiveDetectionsList.innerHTML = `<span class="mono" style="font-size: 11px; color: var(--text-faint);">감지된 객체 없음</span>`;
          }
        }
      }
    } catch {}
  }
  setInterval(updateAiGuardTelemetry, 1500);

  // 조이스틱: 원 안에서 드래그한 만큼 실시간으로 speed/turn을 보낸다(자동차 게임 방식).
  // 방향 버튼(한 번 클릭 -> 그 방향으로 계속 이동)이 답답하다는 피드백(2026-08-26)으로 교체.
  const JOY_FORWARD_MAX = 85; // 실물 라즈봇 PWM 상한(100) 안에서 체감 속도 상향
  const JOY_REVERSE_MAX = 62; // 후진은 카메라 사각지대 때문에 조금 느리게
  const JOY_TURN_MAX = 90;
  const JOY_DEADZONE = 0.10;
  const JOY_SEND_INTERVAL_MS = 40; // 25Hz. 브라우저/라즈봇 모두 안정적인 제어 주기
  const JOY_ACCEL_RATE = 380; // 약 0.22초 만에 최고속도 도달
  const JOY_BRAKE_RATE = 650;
  const JOY_TURN_RATE = 520;

  let joyDragging = false;
  let joyPointerId = null;
  let joyRadius = 0;
  let joyTargetSpeed = 0;
  let joyTargetTurn = 0;
  let joyOutputSpeed = 0;
  let joyOutputTurn = 0;
  let joyLastSentAt = 0;
  let joyLastFrameAt = performance.now();
  let joyCommandInFlight = false;
  let joyQueuedCommand = null;
  let joyLastErrorAt = 0;
  let joyControlActive = false;

  function joySetKnob(dx, dy) {
    joystickKnob.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
  }

  function joyRenderReadout(speed, turn) {
    joystickSpeedEl.textContent = Math.round(speed);
    joystickTurnEl.textContent = Math.round(turn);
  }

  async function joyFlushCommand(command) {
    if (joyCommandInFlight) {
      joyQueuedCommand = command;
      return;
    }
    joyCommandInFlight = true;
    try {
      await window.LabBotRobotConsole.setRobotCommand({ mode: "manual", ...command });
    } catch (err) {
      // 더 최신 입력(주로 정지)이 이전 요청을 취소한 것은 정상 제어 흐름이다.
      if (err?.name === "AbortError") return;
      // 연결이 끊긴 동안 25Hz로 같은 토스트가 쌓이지 않도록 제한한다.
      if (Date.now() - joyLastErrorAt > 3000) {
        joyLastErrorAt = Date.now();
        window.LabBotToast.error("원격조작 연결을 확인해주세요: " + (err.message || err));
      }
    } finally {
      joyCommandInFlight = false;
      if (joyQueuedCommand) {
        const latest = joyQueuedCommand;
        joyQueuedCommand = null;
        joyFlushCommand(latest);
      }
    }
  }

  function joySendCommand(speed, turn, force = false) {
    const command = { speed: Math.round(speed), turn: Math.round(turn) };
    const now = performance.now();
    if (!force && now - joyLastSentAt < JOY_SEND_INTERVAL_MS) {
      joyQueuedCommand = command;
      return;
    }
    joyLastSentAt = now;

    // 정지는 이동 명령 대기열을 추월해 즉시 보낸다.
    if (force && command.speed === 0 && command.turn === 0 && joyCommandInFlight) {
      joyQueuedCommand = null;
      window.LabBotRobotConsole.setRobotCommand({ speed: 0, turn: 0, mode: "manual" })
        .catch((error) => console.warn("긴급 정지 전송 실패:", error));
      return;
    }

    joyFlushCommand(command);
  }

  function joyApplyRadialCurve(nx, ny) {
    const magnitude = Math.min(1, Math.hypot(nx, ny));
    if (magnitude <= JOY_DEADZONE) return { x: 0, y: 0 };
    const remapped = (magnitude - JOY_DEADZONE) / (1 - JOY_DEADZONE);
    // 저속 구간은 정밀하고 끝부분은 빠르게 최대 출력에 도달하는 게임패드 곡선.
    const curved = remapped * 0.62 + remapped * remapped * remapped * 0.38;
    return { x: (nx / magnitude) * curved, y: (ny / magnitude) * curved };
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

    const axes = joyApplyRadialCurve(dx / joyRadius, dy / joyRadius);
    const throttle = -axes.y;
    const speedLimit = throttle >= 0 ? JOY_FORWARD_MAX : JOY_REVERSE_MAX;
    joyTargetSpeed = throttle * speedLimit;
    // 고속에서는 과도한 급회전을 자동 억제하고, 정지 상태에서는 제자리 회전 출력을 유지.
    const steeringLimit = JOY_TURN_MAX * (1 - 0.34 * Math.abs(throttle));
    joyTargetTurn = axes.x * steeringLimit;
    joyControlActive = true;
  }

  function joyEmergencyStop() {
    joyTargetSpeed = 0;
    joyTargetTurn = 0;
    joyOutputSpeed = 0;
    joyOutputTurn = 0;
    joyControlActive = false;
    joyQueuedCommand = null;
    joyRenderReadout(0, 0);
    joySendCommand(0, 0, true);
  }

  function joyEnd(e) {
    if (!joyDragging) return;
    if (e && joyPointerId !== null && e.pointerId !== undefined && e.pointerId !== joyPointerId) return;
    joyDragging = false;
    joyPointerId = null;
    joystickBase.classList.remove("is-dragging");
    joySetKnob(0, 0);
    joyEmergencyStop(); // 손을 떼면 가속 곡선을 건너뛰고 즉시 정지
  }

  function joyOnMove(e) {
    if (!joyDragging || e.pointerId !== joyPointerId) return;
    e.preventDefault();
    joyUpdateFromPointer(e.clientX, e.clientY);
  }

  function joyApproach(current, target, maxDelta) {
    if (current < target) return Math.min(target, current + maxDelta);
    if (current > target) return Math.max(target, current - maxDelta);
    return target;
  }

  function joyControlFrame(now) {
    if (joyControlActive && !robotControlAllowed()) {
      joyEmergencyStop();
    }

    const dt = Math.min(0.05, Math.max(0.001, (now - joyLastFrameAt) / 1000));
    joyLastFrameAt = now;
    if (joyControlActive) {
      const speedRate = Math.abs(joyTargetSpeed) < Math.abs(joyOutputSpeed) ? JOY_BRAKE_RATE : JOY_ACCEL_RATE;
      joyOutputSpeed = joyApproach(joyOutputSpeed, joyTargetSpeed, speedRate * dt);
      joyOutputTurn = joyApproach(joyOutputTurn, joyTargetTurn, JOY_TURN_RATE * dt);
      joyRenderReadout(joyOutputSpeed, joyOutputTurn);
      if (now - joyLastSentAt >= JOY_SEND_INTERVAL_MS) {
        joySendCommand(joyOutputSpeed, joyOutputTurn, true);
      }
    }
    requestAnimationFrame(joyControlFrame);
  }
  requestAnimationFrame(joyControlFrame);

  joystickBase.addEventListener("pointerdown", (e) => {
    if (!robotControlAllowed() || joyDragging) return;
    e.preventDefault();
    joyDragging = true;
    joyPointerId = e.pointerId;
    joystickBase.setPointerCapture(e.pointerId);
    joystickBase.classList.add("is-dragging");
    const rect = joystickBase.getBoundingClientRect();
    joyRadius = rect.width / 2 - joystickKnob.offsetWidth / 2;
    joyUpdateFromPointer(e.clientX, e.clientY);
    joyLastSentAt = 0;
  });
  joystickBase.addEventListener("pointermove", joyOnMove);
  joystickBase.addEventListener("pointerup", joyEnd);
  joystickBase.addEventListener("pointercancel", joyEnd);
  joystickBase.addEventListener("lostpointercapture", joyEnd);
  window.addEventListener("blur", () => joyDragging && joyEnd());
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden || (!joyDragging && !joyControlActive)) return;
    activeKeyboardKeys.clear();
    if (joyDragging) joyEnd();
    else joyEmergencyStop();
    renderKeyboardFeedback("화면 비활성 · 주행 정지", "blocked");
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

  // 화살표 키로 카메라 팬/틸트 조작. 주행(WASD)과 손이 겹치지 않게 나눠뒀다.
  // 누르고 있으면 D패드를 누르고 있는 것과 같은 속도로 연속 이동한다.
  const CAM_KEY_MAP = {
    arrowup: "up", arrowdown: "down", arrowleft: "left", arrowright: "right",
  };
  const camKeysHeld = new Map();  // key -> setInterval 핸들

  // 주행 쪽 WASD 표시등과 같은 방식으로, 지금 어떤 화살표가 눌렸는지 화면에 보여준다.
  const camFeedbackEl = document.getElementById("robotCamKeyboardFeedback");
  const camStatusEl = document.getElementById("robotCamKeyboardStatus");
  const camKeyEls = document.querySelectorAll("[data-cam-key]");
  const CAM_DIRECTION_LABEL = { up: "위로", down: "아래로", left: "왼쪽", right: "오른쪽" };
  let camFeedbackTimer = null;

  function renderCamFeedback(message = "입력 대기", tone = "idle") {
    if (!camFeedbackEl) return;
    camKeyEls.forEach((el) => {
      el.classList.toggle("is-active", camKeysHeld.has(el.dataset.camKey));
    });
    camStatusEl.textContent = message;
    camFeedbackEl.classList.toggle("is-active", tone === "active");
    camFeedbackEl.classList.toggle("is-blocked", tone === "blocked");
  }

  function showTemporaryCamFeedback(message, tone, duration = 900) {
    if (camFeedbackTimer) clearTimeout(camFeedbackTimer);
    renderCamFeedback(message, tone);
    camFeedbackTimer = setTimeout(() => {
      camFeedbackTimer = null;
      if (camKeysHeld.size === 0) renderCamFeedback();
    }, duration);
  }

  // 여러 방향키를 같이 눌렀을 때도 "위로 + 왼쪽"처럼 다 보이게 한다.
  function camActiveLabel() {
    const parts = Array.from(camKeysHeld.keys(), (k) => CAM_DIRECTION_LABEL[CAM_KEY_MAP[k]]);
    return parts.length ? `입력 중 · ${parts.join(" + ")}` : "입력 대기";
  }

  function camKeyStop(key) {
    const timer = camKeysHeld.get(key);
    if (timer) clearInterval(timer);
    camKeysHeld.delete(key);
    const btn = document.querySelector(`[data-cam="${CAM_KEY_MAP[key]}"]`);
    if (btn) btn.classList.remove("is-active");
    if (camKeysHeld.size === 0) renderCamFeedback();
    else renderCamFeedback(camActiveLabel(), "active");
  }

  window.addEventListener("keydown", (e) => {
    const key = e.key.toLowerCase();
    if (!(key in CAM_KEY_MAP)) return;
    if (!robotControlAllowed()) {
      showTemporaryCamFeedback("입력 비활성 · 로봇 콘솔 탭을 여세요", "blocked");
      return;
    }
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
      showTemporaryCamFeedback("입력창 선택됨 · 카메라키 비활성", "blocked");
      return;
    }
    e.preventDefault();           // 화살표로 페이지가 스크롤되는 것을 막는다
    if (camKeysHeld.has(key)) return;  // 키 반복(auto-repeat)으로 타이머가 쌓이지 않게

    const direction = CAM_KEY_MAP[key];
    const btn = document.querySelector(`[data-cam="${direction}"]`);
    if (btn) btn.classList.add("is-active");   // D패드 버튼도 같이 눌린 것처럼 보이게
    camStep(direction);                        // 누르자마자 한 번 즉시 반응
    camKeysHeld.set(key, setInterval(() => camStep(direction), CAM_REPEAT_MS));
    if (camFeedbackTimer) { clearTimeout(camFeedbackTimer); camFeedbackTimer = null; }
    renderCamFeedback(camActiveLabel(), "active");
  });

  window.addEventListener("keyup", (e) => {
    const key = e.key.toLowerCase();
    if (key in CAM_KEY_MAP) camKeyStop(key);
  });

  // 탭 전환 등으로 keyup을 놓치면 카메라가 계속 돌아간다 — 창을 벗어나면 전부 정지.
  window.addEventListener("blur", () => {
    Array.from(camKeysHeld.keys()).forEach(camKeyStop);
    renderCamFeedback("창 포커스 없음 · 카메라 정지", "blocked");
  });

  window.addEventListener("focus", () => {
    if (camKeysHeld.size === 0) renderCamFeedback();
  });

  renderCamFeedback();

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

  // 카메라 각도 원터치 프리셋 버튼 (정면 / 바닥라인 / 상단선반)
  document.querySelectorAll(".cam-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      camPan = parseInt(btn.dataset.pan, 10) || 90;
      camTilt = parseInt(btn.dataset.tilt, 10) || 90;
      camRender();
      camSend();
    });
  });

  // FPV 실시간 HUD 텔레메트리 오버레이 (초음파 거리, 서보 각도, 실시간 안전 경고)
  const robotHudOverlay = document.getElementById("robotHudOverlay");
  const hudDistanceBadge = document.getElementById("hudDistanceBadge");
  const hudSafetyBadge = document.getElementById("hudSafetyBadge");
  const hudFpsBadge = document.getElementById("hudFpsBadge");
  const hudAngleBadge = document.getElementById("hudAngleBadge");
  const hudSpeedBadge = document.getElementById("hudSpeedBadge");

  async function updateHudTelemetry() {
    if (robotCameraMode !== "stream") {
      if (robotHudOverlay) robotHudOverlay.style.display = "none";
      return;
    }
    if (robotHudOverlay) robotHudOverlay.style.display = "flex";

    try {
      const telemetry = await window.LabBotRobotConsole.fetchTelemetry(600);
      if (telemetry) {
        if (telemetry.night_guard) renderNightGuardStatus(telemetry.night_guard);
        const dist = telemetry.distance_cm;
        if (hudDistanceBadge) {
          hudDistanceBadge.innerHTML = `📏 <strong>${dist !== undefined && dist < 900 ? dist.toFixed(1) + " cm" : "측정 중"}</strong>`;
        }
        if (hudSafetyBadge) {
          const avoidance = telemetry.avoidance;
          if (avoidance && avoidance.active) {
            const mustWait = avoidance.state === "wait_person" || avoidance.state === "blocked_wait";
            hudSafetyBadge.className = `hud-tag ${mustWait ? "hud-status-danger" : "hud-status-warning"}`;
            hudSafetyBadge.textContent = `${mustWait ? "🛑" : "↪️"} ${avoidance.label || "장애물 우회 중"}`;
            robotCameraImg.style.borderColor = mustWait ? "#ef4444" : "#f59e0b";
            robotCameraImg.style.boxShadow = mustWait
              ? "0 0 16px rgba(239, 68, 68, 0.7)"
              : "0 0 16px rgba(245, 158, 11, 0.55)";
          } else if (dist !== undefined && dist < 40.0) {
            hudSafetyBadge.className = "hud-tag hud-status-danger";
            hudSafetyBadge.innerHTML = "🛑 전방 장애물 위험!";
            robotCameraImg.style.borderColor = "#ef4444";
            robotCameraImg.style.boxShadow = "0 0 16px rgba(239, 68, 68, 0.7)";
          } else {
            hudSafetyBadge.className = "hud-tag hud-status-ok";
            hudSafetyBadge.innerHTML = "🟢 정상 주행";
            robotCameraImg.style.borderColor = "var(--border)";
            robotCameraImg.style.boxShadow = "none";
          }
        }
        if (hudAngleBadge) {
          hudAngleBadge.textContent = `📐 P: ${telemetry.cam_pan || 90}° · T: ${telemetry.cam_tilt || 90}°`;
        }
        if (hudSpeedBadge) {
          hudSpeedBadge.textContent = `🚗 SPD: ${telemetry.speed || 0} · TRN: ${telemetry.turn || 0}`;
        }
        if (hudFpsBadge) {
          // admin.html에 "⚡ 30 FPS"가 하드코딩돼 있어서, 스트림이 죽어도 30 FPS로
          // 보였다. 실제 값이 있으면 그걸 쓰고 없으면 표시를 지운다.
          hudFpsBadge.textContent = telemetry.fps ? `⚡ ${telemetry.fps} FPS` : "";
        }
      } else {
        // 텔레메트리를 못 받으면 마지막 값을 그대로 두지 않는다 — 죽은 로봇의
        // 거리/속도를 계속 보여주면 운영자가 살아있는 걸로 오인한다.
        if (hudDistanceBadge) hudDistanceBadge.innerHTML = "📏 <strong>—</strong>";
        if (hudAngleBadge) hudAngleBadge.textContent = "📐 P: — · T: —";
        if (hudSpeedBadge) hudSpeedBadge.textContent = "🚗 SPD: — · TRN: —";
        if (hudFpsBadge) hudFpsBadge.textContent = "";
        if (hudSafetyBadge) {
          hudSafetyBadge.className = "hud-tag";
          hudSafetyBadge.innerHTML = "⚠️ 텔레메트리 끊김";
        }
      }
    } catch {}
  }
  setInterval(updateHudTelemetry, 1000);

  // 🩺 로봇 하드웨어 상태 바 — 온도/CPU/메모리/가동시간 + 스로틀 경고.
  // 텔레메트리(1초)보다 훨씬 느리게 돈다. 이 값들은 초 단위로 안 바뀌고,
  // 약한 와이파이에서 폴링을 늘리면 조작 명령이 밀린다.
  const healthEls = {
    bar: document.getElementById("robotHealthBar"),
    temp: document.getElementById("healthTemp"),
    cpu: document.getElementById("healthCpu"),
    mem: document.getElementById("healthMem"),
    uptime: document.getElementById("healthUptime"),
    throttle: document.getElementById("healthThrottle"),
  };

  function formatUptime(sec) {
    if (typeof sec !== "number") return "--";
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d > 0) return `${d}일 ${h}시간`;
    if (h > 0) return `${h}시간 ${m}분`;
    return `${m}분`;
  }

  function setChip(el, text, cls = null) {
    if (!el) return;
    el.querySelector("strong").textContent = text;
    el.classList.remove("is-warm", "is-hot", "is-offline");
    if (cls) el.classList.add(cls);
  }

  async function updateRobotHealth() {
    if (!healthEls.bar) return;
    const h = await window.LabBotRobotConsole.fetchRobotHealth();
    if (!h) {
      // 로봇이 꺼졌거나 와이파이가 끊긴 상태 — 옛날 숫자를 그대로 두면 오해를 부른다.
      ["temp", "cpu", "mem", "uptime"].forEach((k) => setChip(healthEls[k], "--", "is-offline"));
      healthEls.throttle.style.display = "none";
      return;
    }

    // 온도: Pi 5는 80도에서 소프트 온도 제한이 걸려 클럭이 떨어진다.
    const t = h.temp_c;
    setChip(healthEls.temp, t == null ? "--" : `${t}°C`,
      t == null ? "is-offline" : t >= 75 ? "is-hot" : t >= 65 ? "is-warm" : null);

    const load = h.load_pct;
    const mhz = h.cpu_mhz;
    setChip(healthEls.cpu,
      load == null ? "--" : `${load}%${mhz ? ` · ${(mhz / 1000).toFixed(1)}GHz` : ""}`,
      load == null ? "is-offline" : load >= 90 ? "is-hot" : load >= 70 ? "is-warm" : null);

    const mem = h.mem_used_pct;
    setChip(healthEls.mem,
      mem == null ? "--" : `${mem}%${h.mem_total_mb ? ` / ${(h.mem_total_mb / 1024).toFixed(1)}GB` : ""}`,
      mem == null ? "is-offline" : mem >= 90 ? "is-hot" : mem >= 75 ? "is-warm" : null);

    setChip(healthEls.uptime, formatUptime(h.uptime_sec), h.uptime_sec == null ? "is-offline" : null);

    // 지금 걸려 있는 스로틀만 보여준다(이력 비트는 제외). 없으면 칩 자체를 숨긴다.
    const active = Array.isArray(h.throttled_now) ? h.throttled_now : [];
    if (active.length) {
      healthEls.throttle.style.display = "";
      healthEls.throttle.querySelector("strong").textContent = active.map((f) => f.label).join(" · ");
    } else {
      healthEls.throttle.style.display = "none";
    }
  }

  // 키보드 원격 운전 단축키 (WASD / 방향키 / Space 긴급정지)
  const activeKeyboardKeys = new Set();
  let keyboardFeedbackTimer = null;

  // 화살표 키는 주행이 아니라 카메라 팬/틸트에 쓴다(아래 카메라 키 핸들러 참고).
  // 주행은 WASD 전용 — 한 손은 주행, 다른 손은 카메라로 나뉘어야 조작이 겹치지 않는다.
  function canonicalDriveKey(key) {
    return key;
  }

  function renderKeyboardFeedback(message = "입력 대기", tone = "idle") {
    const pressedKeys = new Set(Array.from(activeKeyboardKeys, canonicalDriveKey));
    keyboardKeyEls.forEach((keyEl) => {
      keyEl.classList.toggle("is-active", pressedKeys.has(keyEl.dataset.controlKey));
    });
    keyboardStatusEl.textContent = message;
    keyboardFeedbackEl.classList.toggle("is-active", tone === "active");
    keyboardFeedbackEl.classList.toggle("is-stop", tone === "stop");
    keyboardFeedbackEl.classList.toggle("is-blocked", tone === "blocked");
  }

  function showTemporaryKeyboardFeedback(message, tone, duration = 900) {
    if (keyboardFeedbackTimer) clearTimeout(keyboardFeedbackTimer);
    renderKeyboardFeedback(message, tone);
    keyboardFeedbackTimer = setTimeout(() => {
      keyboardFeedbackTimer = null;
      if (activeKeyboardKeys.size === 0) renderKeyboardFeedback();
    }, duration);
  }

  function updateKeyboardDrive() {
    const forward = activeKeyboardKeys.has("w");
    const reverse = activeKeyboardKeys.has("s");
    const left = activeKeyboardKeys.has("a");
    const right = activeKeyboardKeys.has("d");

    const throttle = Number(forward) - Number(reverse);
    const steering = Number(right) - Number(left);
    joyTargetSpeed = throttle >= 0 ? throttle * JOY_FORWARD_MAX : throttle * JOY_REVERSE_MAX;
    joyTargetTurn = steering * JOY_TURN_MAX * (throttle === 0 ? 1 : 0.68);
    joyControlActive = throttle !== 0 || steering !== 0;

    if (!joyControlActive) {
      joyEmergencyStop();
      if (activeKeyboardKeys.size > 0) renderKeyboardFeedback("상반된 키 입력 · 정지", "blocked");
      else renderKeyboardFeedback();
    } else {
      joyLastSentAt = 0;
      const actions = [];
      if (throttle > 0) actions.push("전진");
      if (throttle < 0) actions.push("후진");
      if (steering < 0) actions.push("좌회전");
      if (steering > 0) actions.push("우회전");
      renderKeyboardFeedback(`입력 중 · ${actions.join(" + ")}`, "active");
    }
  }

  // 이 리스너는 DOMContentLoaded 시점에 window에 붙는데, 관리자 권한 확인은 훨씬
  // 뒤에서 끝난다. 그 사이(그리고 권한이 없는 사용자에게도) 키 입력이 그대로 로봇의
  // /drive로 나가는 걸 막아야 한다. 로봇 콘솔 탭을 보고 있을 때만 조작을 허용한다.
  function robotControlAllowed() {
    const panel = document.getElementById("adminPanel");
    if (!panel || panel.style.display === "none") return false;   // 권한 없음 화면
    // Robot Console은 안전 탭(admin.html #tab-safety) 안에 있다.
    const safetyPanel = document.getElementById("tab-safety");
    return !!(safetyPanel && safetyPanel.classList.contains("active"));
  }

  renderKeyboardFeedback();

  window.addEventListener("keydown", (e) => {
    const key = e.key.toLowerCase();
    const isDriveKey = ["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", " "].includes(key);
    if (!isDriveKey) return;
    if (!robotControlAllowed()) {
      renderKeyboardFeedback("입력 비활성 · 로봇 콘솔 탭을 여세요", "blocked");
      return;
    }
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
      renderKeyboardFeedback("입력창 선택됨 · 주행키 비활성", "blocked");
      return;
    }

    e.preventDefault();
    // 비상정지(Space)는 중복 방지 가드보다 먼저 처리한다. 가드에 걸리면 두 번째
    // Space부터 아무 명령도 안 나가서 비상정지가 페이지당 1회만 먹는다.
    if (key === " ") {
      if (e.repeat) return;
      activeKeyboardKeys.clear();
      joyEmergencyStop();
      showTemporaryKeyboardFeedback("긴급 정지 입력됨", "stop");
      return;
    }
    if (activeKeyboardKeys.has(key)) return;
    activeKeyboardKeys.add(key);
    updateKeyboardDrive();
  });

  window.addEventListener("keyup", (e) => {
    const key = e.key.toLowerCase();
    if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright"].includes(key)) {
      if (activeKeyboardKeys.delete(key)) updateKeyboardDrive();
    }
  });

  window.addEventListener("blur", () => {
    if (activeKeyboardKeys.size > 0) {
      activeKeyboardKeys.clear();
      joyEmergencyStop();
    }
    renderKeyboardFeedback("창 포커스 없음 · 주행 정지", "blocked");
  });

  window.addEventListener("focus", () => {
    if (activeKeyboardKeys.size === 0) renderKeyboardFeedback();
  });

  robotAutoBtn.addEventListener("click", async () => {
    try {
      activeKeyboardKeys.clear();
      joyDragging = false;
      joystickBase.classList.remove("is-dragging");
      joySetKnob(0, 0);
      joyEmergencyStop();
      renderKeyboardFeedback("자동순찰 중 · 키 입력 시 수동 전환");
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
    setInterval(refreshRobotModeBadge, 2000);
    updateRobotHealth();
    setInterval(updateRobotHealth, 10000);

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
        <td>${window.LabBotItems.escapeHtml(s.performed_by)}</td>
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

  // 탭을 눌러도 데이터를 다시 안 불러서, 안전 이벤트를 처리하고 다른 탭에 갔다
  // 돌아와도 옛날 목록이 그대로였다(새로고침해야만 갱신됨). 탭별 렌더를 다시 돌린다.
  const TAB_RENDERERS = {
    stock: () => renderStockTable(),
    history: () => renderHistoryTable(),
    damage: () => renderDamageTable(),
    safety: () => renderSafetyTable(),
    audit: () => Promise.all([renderAuditChecklist(), renderAuditSessions()]),
    inquiry: () => renderInquiryCards(),
    users: () => renderUserTable(),
    stats: () => renderStatsPanel(),
  };

  function switchTab(target) {
    tabButtons.forEach((b) => b.classList.remove("active"));
    tabPanels.forEach((p) => p.classList.remove("active"));

    document.querySelector(`.tab-btn[data-tab="${target}"]`).classList.add("active");
    document.getElementById(`tab-${target}`).classList.add("active");

    const render = TAB_RENDERERS[target];
    if (render) {
      Promise.resolve(render()).catch((err) =>
        console.debug("LabBot: 탭 갱신 실패", target, err)
      );
    }
    // 요약 카드도 같이 갱신 — 안전 이벤트를 처리했는데 "검토 필요 3"이 그대로
    // 남아 있는 문제를 막는다.
    if (typeof renderSummaryCards === "function") {
      Promise.resolve(renderSummaryCards()).catch(() => {});
    }
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
      const visibleSafetyEvents = window.LabBotSafety
        .collapseRepeatedSafetyEvents(safetyEvents)
        .filter(window.LabBotSafety.isActionableSafetyEvent);
      document.getElementById("summaryNeedsReview").textContent = visibleSafetyEvents.filter(
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

  // ---------- 통계 (관리자 일상 운영 파악용) ----------
  // 인기 장비 Top5 / 카테고리별 대여 현황 / 연체율은 loans(+items 조인) 하나로 전부 계산되고,
  // 실사 정확도 추이는 audit_sessions를 재사용한다 — 새 테이블/RPC 없이 기존 데이터 재집계만으로 충분하다.
  async function renderStatsPanel() {
    let loans, auditSessions;
    try {
      [loans, auditSessions] = await Promise.all([
        window.LabBotRentals.fetchAllLoans(),
        window.LabBotAudit.fetchAuditSessions(),
      ]);
    } catch (err) {
      window.LabBotToast.error("통계를 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const { escapeHtml } = window.LabBotItems;
    // 취소된 예약은 실제 대여로 안 친다 — mypage.js의 총 대여횟수 집계와 같은 기준.
    const validLoans = loans.filter((l) => l.status !== "취소됨");

    document.getElementById("statsTotalLoans").textContent = validLoans.length;

    // 연체율 — "지금 당장 챙겨야 할 문제"가 반납 완료건에 희석되지 않도록, 현재 대여중인
    // 건만 놓고 그중 연체 비율을 낸다(요약 카드의 summaryOverdueUsers와 같은 관점).
    const activeLoans = validLoans.filter((l) => l.status === "대여중");
    const overdueCount = activeLoans.filter((l) => window.LabBotRentals.isOverdue(l)).length;
    document.getElementById("statsOverdueRate").textContent =
      activeLoans.length === 0 ? "0%" : `${Math.round((overdueCount / activeLoans.length) * 100)}%`;

    // 장비 대여 사용량 — 한 번이라도 대여된 물품 전체를 건수 순으로. Top N으로 자르면
    // "적게 쓰이는 장비"를 못 보게 되는데, 그것도 운영 판단(추가구매/처분)에 필요한 정보다.
    // 목록이 길어질 수 있어서 표 컨테이너에 max-height(.stats-scroll-table)를 줬다.
    const itemCounts = new Map(); // item_id -> { name, category, count }
    validLoans.forEach((l) => {
      if (!l.items) return; // 삭제된 물품 참조 등
      const entry = itemCounts.get(l.item_id) || { name: l.items.name, category: l.items.category, count: 0 };
      entry.count += 1;
      itemCounts.set(l.item_id, entry);
    });
    const topItems = [...itemCounts.values()].sort((a, b) => b.count - a.count);

    const topItemsBody = document.getElementById("statsTopItemsBody");
    topItemsBody.innerHTML =
      topItems.length === 0
        ? `<tr><td colspan="3" class="mono" style="text-align:center; padding: 20px;">대여 이력이 없습니다.</td></tr>`
        : topItems
            .map((it) => `<tr><td>${escapeHtml(it.name)}</td><td>${escapeHtml(it.category || "-")}</td><td>${it.count}건</td></tr>`)
            .join("");

    // 카테고리별 대여 현황 — 비율의 분모는 validLoans.length가 아니라 "카테고리를 알 수 있는
    // 건수"의 합이어야 한다. 물품이 삭제된 대여 건(items가 null)은 어느 카테고리에도 안 들어가는데
    // 분모에만 남으면 비율 합이 100%가 안 되고(예: 75%+13%=88%) 표가 틀린 것처럼 보인다.
    const categoryCounts = new Map();
    validLoans.forEach((l) => {
      if (!l.items) return;
      const cat = l.items.category || "미분류";
      categoryCounts.set(cat, (categoryCounts.get(cat) || 0) + 1);
    });
    const categoryRows = [...categoryCounts.entries()].sort((a, b) => b[1] - a[1]);
    const categorizedTotal = categoryRows.reduce((sum, [, count]) => sum + count, 0);

    const categoryBody = document.getElementById("statsCategoryBody");
    categoryBody.innerHTML =
      categoryRows.length === 0
        ? `<tr><td colspan="3" class="mono" style="text-align:center; padding: 20px;">대여 이력이 없습니다.</td></tr>`
        : categoryRows
            .map(
              ([cat, count]) =>
                `<tr><td>${escapeHtml(cat)}</td><td>${count}건</td><td>${Math.round((count / categorizedTotal) * 100)}%</td></tr>`
            )
            .join("");

    // 재고 실사 정확도 추이 (최신순 5건) — audit_sessions는 이미 "재고 실사" 탭에서 전체
    // 이력을 보여주므로, 여기서는 최근 흐름만 요약하고 전체는 그쪽 탭으로 안내한다.
    const recentSessions = [...auditSessions].sort((a, b) => new Date(b.started_at) - new Date(a.started_at)).slice(0, 5);
    const accuracyOf = (s) => (s.scanned_count === 0 ? null : Math.round(((s.scanned_count - s.mismatch_count) / s.scanned_count) * 100));

    const latestAcc = recentSessions.length === 0 ? null : accuracyOf(recentSessions[0]);
    document.getElementById("statsLatestAccuracy").textContent = latestAcc === null ? "-" : `${latestAcc}%`;

    const auditBody = document.getElementById("statsAuditTrendBody");
    auditBody.innerHTML =
      recentSessions.length === 0
        ? `<tr><td colspan="5" class="mono" style="text-align:center; padding: 20px;">실사 이력이 없습니다.</td></tr>`
        : recentSessions
            .map((s) => {
              const acc = accuracyOf(s);
              return `<tr><td class="mono">${new Date(s.started_at).toLocaleDateString("ko-KR")}</td><td>${escapeHtml(s.performed_by)}</td><td>${s.scanned_count}개</td><td>${s.mismatch_count}개</td><td>${acc === null ? "-" : acc + "%"}</td></tr>`;
            })
            .join("");
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
    await renderStatsPanel();
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
