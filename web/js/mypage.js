// LabBot - 마이페이지 스크립트 (Supabase loans 테이블 연동)

document.addEventListener("DOMContentLoaded", async () => {
  const session = await window.LabBotAuth.requireLogin("mypage.html");
  if (!session) return;

  const profileAvatar = document.getElementById("profileAvatar");
  const profileName = document.getElementById("profileName");
  const profileEmail = document.getElementById("profileEmail");
  const profileRole = document.getElementById("profileRole");
  const statActiveCount = document.getElementById("statActiveCount");
  const statTotalCount = document.getElementById("statTotalCount");

  const reservedListEl = document.getElementById("reservedRentalList");
  const reservedEmptyEl = document.getElementById("reservedRentalEmpty");
  const activeListEl = document.getElementById("activeRentalList");
  const activeEmptyEl = document.getElementById("activeRentalEmpty");
  const historyBodyEl = document.getElementById("rentalHistoryBody");
  const historyEmptyEl = document.getElementById("rentalHistoryEmpty");
  const inquiryListEl = document.getElementById("inquiryList");
  const inquiryEmptyEl = document.getElementById("inquiryEmpty");
  const inquiryPaginationEl = document.getElementById("inquiryPagination");
  const INQUIRY_PAGE_SIZE = 10;
  let inquiryPage = 1;

  const restockListEl = document.getElementById("restockList");
  const restockEmptyEl = document.getElementById("restockEmpty");

  profileAvatar.textContent = session.name.trim().charAt(0).toUpperCase() || "?";
  profileName.textContent = session.name;
  profileEmail.textContent = session.email;
  profileRole.textContent = session.role === "admin" ? "관리자" : "일반 사용자";

  function formatDateTime(iso) {
    return new Date(iso).toLocaleString("ko-KR", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function daysSince(iso) {
    const diffMs = Date.now() - new Date(iso).getTime();
    return Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
  }

  // 예약중 카드 — "수령하기"/"사용하기"를 누르면 로봇 안내 화면(openGuideModal)으로 넘어간다.
  // 이 단계에서는 아직 실제로 받아간 게 아니라서 due_at이 없다(반납예정일 표시 안 함).
  // 소모품은 장비와 달리 "몇 개 쓸지"를 여기서 먼저 정한 뒤 QR 확인으로 넘어간다.
  function renderReservedCard(loan) {
    const item = loan.items;
    const { escapeHtml } = window.LabBotItems;
    const consumable = window.LabBotRentals.isConsumable(item);
    // 예약 시점에 이미 1개가 임시로 차감돼 있으므로(공용 트리거), 이 사용자가 실제로
    // 고를 수 있는 최대치는 지금 남은 재고 + 자기 몫 1개다.
    const maxQty = consumable ? item.available_qty + 1 : null;

    const actionHtml = consumable
      ? `
        <div class="qty-stepper">
          <label for="qty-input-${loan.id}">사용 수량</label>
          <input type="number" id="qty-input-${loan.id}" min="1" max="${maxQty}" value="1" />
          <span class="qty-unit">${escapeHtml(item.unit || "개")}</span>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" data-cancel-loan="${loan.id}">예약 취소</button>
        <button type="button" class="btn btn-primary btn-sm" data-use-loan="${loan.id}">사용하기</button>
      `
      : `
        <button type="button" class="btn btn-secondary btn-sm" data-cancel-loan="${loan.id}">예약 취소</button>
        <button type="button" class="btn btn-primary btn-sm" data-pickup-loan="${loan.id}">수령하기</button>
      `;

    const card = document.createElement("article");
    card.className = "rental-card rental-card-reserved";
    card.innerHTML = `
      <div class="rental-card-main">
        <span class="category-tag">${escapeHtml(window.LabBotItems.categoryLabelOf(item.category))}</span>
        <h3 class="rental-card-name">${escapeHtml(item.name)}</h3>
        <span class="item-row-location">${escapeHtml(item.location)}</span>
      </div>
      <div class="rental-card-meta">
        <span class="rental-card-date">예약일 ${formatDateTime(loan.borrowed_at)}</span>
        <span class="badge badge-pending"><span class="badge-dot"></span>${consumable ? "사용 대기" : "수령 대기"}</span>
        ${actionHtml}
      </div>
    `;

    if (consumable) {
      card.querySelector("[data-use-loan]").addEventListener("click", () => {
        const qtyInput = card.querySelector(`#qty-input-${loan.id}`);
        const qty = parseInt(qtyInput.value, 10);
        if (!Number.isFinite(qty) || qty < 1) {
          window.LabBotToast.error("사용 수량을 1 이상으로 입력해주세요.");
          return;
        }
        if (maxQty !== null && qty > maxQty) {
          window.LabBotToast.error(`남은 재고(${maxQty}${item.unit || "개"})보다 많이 사용할 수 없습니다.`);
          return;
        }
        openGuideModal({ loan, mode: "use", qty });
      });
    } else {
      card.querySelector("[data-pickup-loan]").addEventListener("click", () => {
        openGuideModal({ loan, mode: "pickup" });
      });
    }

    // 예약 취소 — 잘못 예약했을 때 되돌리는 용도. 삭제 확인은 다른 파괴적 작업(관리자
    // 물품 삭제 등)과 같이 네이티브 confirm()을 그대로 쓴다.
    card.querySelector("[data-cancel-loan]").addEventListener("click", async (e) => {
      if (!confirm(`"${item.name}" 예약을 취소하시겠습니까?`)) return;
      const button = e.currentTarget;
      button.disabled = true;
      try {
        await window.LabBotRentals.cancelReservation(loan.id);
        window.LabBotToast.success(`"${item.name}" 예약이 취소되었습니다.`);
        await renderAll();
      } catch (err) {
        window.LabBotToast.error(err.message || "예약 취소에 실패했습니다.");
        button.disabled = false;
      }
    });

    return card;
  }

  function renderActiveCard(loan) {
    const item = loan.items;
    const overdue = window.LabBotRentals.isOverdue(loan);
    const elapsed = daysSince(loan.borrowed_at);

    const card = document.createElement("article");
    card.className = `rental-card${overdue ? " rental-card-overdue" : ""}`;
    const { escapeHtml } = window.LabBotItems;
    card.innerHTML = `
      <div class="rental-card-main">
        <span class="category-tag">${escapeHtml(window.LabBotItems.categoryLabelOf(item.category))}</span>
        <h3 class="rental-card-name">${escapeHtml(item.name)}</h3>
        <span class="item-row-location">${escapeHtml(item.location)}</span>
      </div>
      <div class="rental-card-meta">
        <span class="rental-card-date">대여일 ${formatDateTime(loan.borrowed_at)} · ${elapsed}일째 · 반납예정 ${formatDateTime(loan.due_at)}</span>
        ${
          overdue
            ? '<span class="badge badge-overdue"><span class="badge-dot"></span>연체</span>'
            : '<span class="badge badge-available"><span class="badge-dot"></span>대여중</span>'
        }
        <button type="button" class="btn btn-secondary btn-sm" data-report-damage>파손 신고</button>
        <button type="button" class="btn btn-secondary btn-sm" data-return-loan="${loan.id}">반납하기</button>
      </div>
    `;

    card.querySelector("[data-return-loan]").addEventListener("click", () => {
      openGuideModal({ loan, mode: "return" });
    });

    card.querySelector("[data-report-damage]").addEventListener("click", () => {
      openDamageReportModal(item, session);
    });

    return card;
  }

  // ---------- 로봇 안내 + QR 확인 모달 (수령/반납/소모품 사용 공용) ----------
  // "대여하기"/"사용하기"를 눌러도 그 자리에서 바로 끝나지 않는다 — 로봇이 있는 곳까지
  // 안내를 받고 물품 QR을 스캔해야만 실제로 확정된다. mode: "pickup"(장비 수령),
  // "return"(반납), "use"(소모품 사용, qty 필요) 셋 다 이 모달 하나로 처리한다. QR 대조는
  // confirm_loan_pickup/return/confirm_item_usage RPC가 서버에서 한 번 더 하므로, 카메라를
  // 속여도 실제로는 통과하지 못한다.
  const GUIDE_COPY = {
    pickup: { eyebrow: "물품 수령", message: "로봇을 따라가세요" },
    return: { eyebrow: "물품 반납", message: "로봇에게 돌아가세요" },
    use: { eyebrow: "물품 사용", message: "로봇을 따라가세요" },
  };

  // 물품 목록에서 예약하고 넘어오면 ?guide=1&loanId=... 가 붙어 있다. 그때는
  // 사용자가 목록에서 다시 찾아 누르게 하지 않고 바로 안내창을 연다 - 방금
  // 누른 그 물품을 다시 고르게 하는 건 불필요한 단계다.
  function openGuideFromQuery(loans) {
    const q = new URLSearchParams(window.location.search);
    if (q.get("guide") !== "1") return;
    const loanId = q.get("loanId");
    const loan = (loans || []).find((l) => String(l.id) === String(loanId));
    // 주소창을 정리해 새로고침 때 또 열리지 않게 한다.
    window.history.replaceState({}, "", window.location.pathname);
    if (!loan) return;
    const item = loan.items || {};
    // item_type 은 DB 에서 대문자다(CONSUMABLE/EQUIPMENT/...). 직접 문자열을
    // 비교하면 절대 안 맞는다 - 다른 화면들이 쓰는 헬퍼를 그대로 쓴다.
    const consumable = window.LabBotRentals.isConsumable(item);
    openGuideModal({ loan, mode: consumable ? "use" : "pickup", qty: 1 });
  }

  function openGuideModal({ loan, mode, qty }) {
    const item = loan.items;
    const copy = GUIDE_COPY[mode];
    const { escapeHtml } = window.LabBotItems;

    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card guide-modal-card">
        <div class="guide-step" data-step="nav">
          <div class="guide-scanline-box">
            <p class="guide-eyebrow">${copy.eyebrow} · 로봇 자동 안내</p>
            <h3 class="guide-message">${copy.message}</h3>
            <p class="guide-caption" id="guideNavStatus">물품 좌표를 확인하고 있습니다...</p>
          </div>
          <p class="guide-item-name">${escapeHtml(item.name)} · ${escapeHtml(item.location)}${
            mode === "use" ? ` · ${qty}${escapeHtml(item.unit || "개")}` : ""
          }</p>
          <p class="guide-sim-note mono">실물 로봇이 선반으로 이동합니다 · QR을 찍으면 로봇은 대기 자리로 돌아갑니다</p>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-action="cancel">안내 취소</button>
            <button type="button" class="btn btn-primary btn-sm" data-action="to-scan">물품을 들었어요 · 로봇 QR 스캔</button>
          </div>
        </div>

        <div class="guide-step" data-step="scan" hidden>
          <p class="guide-eyebrow">물품 QR 보여주기 · 실물 로봇</p>
          <p class="guide-caption">${escapeHtml(item.name)}의 QR입니다. 이 화면을 로봇 카메라 정면에 대주세요</p>
          <!-- 로봇 카메라 화면이 아니라 물품 QR 을 띄운다. QR 을 읽는 쪽은
               로봇이므로, 사람은 보여줄 것이 필요하지 볼 것이 필요한 게 아니다. -->
          <div class="qr-show-frame">
            <canvas id="guideItemQr" width="220" height="220"></canvas>
            <p class="qr-show-code mono" id="guideItemQrCode"></p>
          </div>
          <details class="qr-robot-view">
            <summary>로봇이 보는 화면 확인</summary>
            <div class="qr-scan-frame">
              <img class="qr-scan-video" id="guideRobotCamera" alt="로봇 카메라 화면" />
              <div class="qr-scan-reticle"></div>
            </div>
          </details>
          <p class="guide-scan-status" id="guideScanStatus">QR을 로봇 카메라에 대고 아래 버튼을 누르세요.</p>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-action="back-to-guide">안내 상태 보기</button>
            <button type="button" class="btn btn-primary btn-sm" data-action="robot-scan">로봇으로 QR 읽기</button>
          </div>
          <div class="guide-manual-fallback">
            <label for="guideManualInput">로봇 카메라가 안 되면 QR 코드를 직접 입력하세요</label>
            <div class="guide-manual-row">
              <input type="text" id="guideManualInput" placeholder="예: LB-XXXXXXXX" autocomplete="off" />
              <button type="button" class="btn btn-secondary btn-sm" data-action="manual-confirm">확인</button>
            </div>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-action="cancel">취소</button>
          </div>
        </div>

        <div class="guide-step" data-step="success" hidden>
          <p class="guide-message">✅ 확인되었습니다</p>
          <p class="guide-caption" data-success-caption></p>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    let submitting = false;
    let closed = false;
    let guideCompleted = false;
    let guidePollTimer = null;

    function showStep(name) {
      overlay.querySelectorAll("[data-step]").forEach((el) => {
        el.hidden = el.dataset.step !== name;
      });
    }

    function close() {
      if (closed) return;
      closed = true;
      if (guidePollTimer) clearInterval(guidePollTimer);
      if (!guideCompleted) window.LabBotRobotConsole.finishRobotGuide("cancelled").catch(() => null);
      overlay.remove();
    }

    overlay.querySelectorAll('[data-action="cancel"]').forEach((btn) =>
      btn.addEventListener("click", async () => {
        // 창만 닫으면 로봇은 선반 앞에 계속 서 있는다. 취소는 로봇도 멈춰야
        // 취소다. 실패해도 창은 닫는다 - 로봇이 안 멈췄다고 사용자를 창에
        // 가둬둘 이유가 없다(대기 자리 복귀 버튼이 따로 있다).
        try {
          await window.LabBotRobotConsole.cancelDelivery();
        } catch (err) {
          console.warn("[guide] 로봇 정지 실패:", err);
        }
        close();
      }));
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(); // 배경 클릭으로도 닫히게(진행 중인 예약/대여는 그대로 유지됨)
    });

    const scanStatus = overlay.querySelector("#guideScanStatus");
    const manualInput = overlay.querySelector("#guideManualInput");
    const navStatus = overlay.querySelector("#guideNavStatus");
    const robotCamera = overlay.querySelector("#guideRobotCamera");

    // 물품 QR 을 화면에 그린다.
    //
    // QR 값은 item_qr_codes 에 있고, 자기가 예약중·대여중인 물품만 읽을 수
    // 있다(RLS). 전부 열지 않는 이유는 QR 하나면 그 물품 수령이 확정되기
    // 때문이다 - 아무나 읽으면 남의 예약을 가로챌 수 있다.
    //
    // 그래도 값이 없을 수 있다(마이그레이션 전이거나 예약이 만료된 경우).
    // 그때는 직접 입력으로 넘어가게 둔다 - 값이 없다고 대여를 막으면 안 된다.
    function renderItemQr() {
      const canvas = overlay.querySelector("#guideItemQr");
      const codeText = overlay.querySelector("#guideItemQrCode");
      if (!canvas || !codeText) return;
      const code = window.LabBotItems.qrCodeOf(item);
      if (!code) {
        canvas.style.display = "none";
        codeText.textContent = "QR 값을 불러오지 못했습니다 · 물품에 붙은 QR 라벨을 로봇에 보여주거나 아래에 직접 입력하세요";
        return;
      }
      codeText.textContent = code;
      if (!window.QRCode) {
        codeText.textContent = code + " (QR 그리기 실패 — 위 코드를 직접 입력하세요)";
        return;
      }
      window.QRCode.toCanvas(canvas, code, { width: 220, margin: 1 }, (err) => {
        if (err) {
          canvas.style.display = "none";
          codeText.textContent = code + " (QR 그리기 실패 — 위 코드를 직접 입력하세요)";
        }
      });
    }

    function renderGuideStatus(status) {
      if (!status) return;
      const exactLocation = status.location_detail || `${status.shelf_code || "물품 위치"} 선반`;
      // 로봇이 이동할 수 없는 상태(바퀴 잠금·고장·충전 중)면 그렇다고 말한다.
      // 안 그러면 사용자가 오지 않는 로봇을 계속 기다린다. 대여 자체는
      // QR 확인으로 진행되므로 무엇을 하면 되는지 같이 알려준다.
      if (status.drive && status.drive.phase === "stationary") {
        navStatus.textContent =
          `로봇이 지금 이동할 수 없습니다 · 물품 위치: ${exactLocation}`
          + " · 물품을 가져와 아래 QR을 로봇 카메라에 보여주면 대여가 확정됩니다.";
        return;
      }
      if (status.status === "arrived") {
        navStatus.textContent = `도착했습니다 · ${exactLocation}에 물품이 있습니다. 물품을 꺼낸 뒤 로봇 카메라에 QR을 보여주세요.`;
      } else if (status.status === "navigating") {
        navStatus.textContent = `로봇을 따라가세요 · 목적지: ${exactLocation} · 이동 ${status.waypoint_index + 1}/${status.waypoint_count}`;
      } else if (status.status === "awaiting_route_calibration") {
        navStatus.textContent = `물품 위치: ${exactLocation} · 실물 로봇 경로는 현장 캘리브레이션 대기 중입니다. QR은 현재 위치에서 바로 보여줘도 됩니다.`;
      } else if (status.status === "awaiting_route_executor") {
        navStatus.textContent = `물품 위치: ${exactLocation} · 검증된 실물 경로 실행기가 아직 연결되지 않아 로봇은 안전 정지 상태입니다. QR은 현재 위치에서 바로 보여줘도 됩니다.`;
      } else if (status.status === "idle") {
        navStatus.textContent = "안내 대기 중";
      }
    }

    async function beginRobotGuide() {
      try {
        const ip = await window.LabBotRobotConsole.fetchRobotIp();
        robotCamera.src = window.LabBotRobotConsole.getDirectStreamUrl(ip);
        const result = await window.LabBotRobotConsole.startRobotGuide({ loanId: loan.id, item, mode });
        renderGuideStatus(result);
        guidePollTimer = setInterval(async () => {
          try {
            renderGuideStatus(await window.LabBotRobotConsole.fetchRobotGuideStatus());
          } catch {}
        }, 750);
      } catch (err) {
        navStatus.textContent = `자동 안내 연결 실패 · ${err.message || err}`;
      }
    }

    async function submitCode(code, codeType = "qr") {
      scanStatus.textContent = "QR과 AI 카메라 물품을 함께 확인 중...";
      try {
        const visionCheck = await window.LabBotRobotConsole.verifyCheckoutItem(item);
        if (visionCheck?.verdict === "blocked") {
          const found = (visionCheck.detected_items || []).join(", ") || "다른 물품";
          throw new Error(`AI 확인 보류: ${found}이(가) 함께 보이거나 예약 물품과 다릅니다. 예약 물품 하나만 카메라 중앙에 보여주세요.`);
        }
        const isVirtual = codeType === "scene_object_id";
        if (mode === "pickup") {
          if (isVirtual) await window.LabBotRentals.confirmVirtualPickup(loan.id, code);
          else await window.LabBotRentals.confirmPickup(loan.id, code);
        } else if (mode === "return") {
          if (isVirtual) await window.LabBotRentals.confirmVirtualReturn(loan.id, code);
          else await window.LabBotRentals.confirmReturn(loan.id, code);
        } else {
          if (isVirtual) await window.LabBotRentals.confirmVirtualUsage(loan.id, code, qty);
          else await window.LabBotRentals.confirmUsage(loan.id, code, qty);
        }
        guideCompleted = true;
        if (guidePollTimer) clearInterval(guidePollTimer);
        await window.LabBotRobotConsole.finishRobotGuide("completed").catch(() => null);

        const successCaption =
          mode === "pickup"
            ? "대여가 시작되었습니다. 반납예정일은 대여 목록에서 확인하세요."
            : mode === "return"
              ? "반납이 완료되었습니다."
              : `${qty}${item.unit || "개"} 사용 처리되었습니다.`;
        const toastMessage =
          mode === "pickup"
            ? `"${item.name}" 대여가 시작되었습니다.`
            : mode === "return"
              ? `"${item.name}" 반납이 완료되었습니다.`
              : `"${item.name}" ${qty}${item.unit || "개"} 사용 처리되었습니다.`;

        overlay.querySelector("[data-success-caption]").textContent = successCaption;
        showStep("success");
        window.LabBotToast.success(toastMessage);
        setTimeout(async () => {
          close();
          await renderAll();
        }, 1400);
      } catch (err) {
        const message = err.message || "확인에 실패했습니다. 다시 스캔해주세요.";
        scanStatus.textContent = message;
        // QR 코드가 이 대여 건의 물품이 아닐 때(서버 RPC의 qr_code 불일치 예외) —
        // 화면 하단 문구만으로는 놓치기 쉬워서 토스트로도 눈에 띄게 알려준다.
        if (message.includes("일치하지 않습니다")) {
          window.LabBotToast.error(`다른 물품입니다 — "${item.name}"의 QR 코드가 아니에요.`);
        }
      }
    }

    overlay.querySelector('[data-action="manual-confirm"]').addEventListener("click", () => {
      const code = manualInput.value.trim();
      if (!code) return;
      submitCode(code);
    });
    manualInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") overlay.querySelector('[data-action="manual-confirm"]').click();
    });

    overlay.querySelector('[data-action="to-scan"]').addEventListener("click", async () => {
      showStep("scan");
      renderItemQr();   // 이 단계에 들어와야 캔버스가 보이므로 여기서 그린다
    });

    overlay.querySelector('[data-action="back-to-guide"]').addEventListener("click", () => showStep("nav"));
    overlay.querySelector('[data-action="robot-scan"]').addEventListener("click", async () => {
      if (submitting) return;
      submitting = true;
      scanStatus.textContent = "로봇 카메라에서 QR을 읽는 중...";
      try {
        const result = await window.LabBotRobotConsole.triggerQrScan();
        if (!result.found) throw new Error(result.message || "QR을 찾지 못했습니다.");
        if (result.code_type === "zone") throw new Error("구역 표식이 아니라 물품 QR을 카메라에 보여주세요.");
        await submitCode(result.code, result.code_type || "qr");
      } catch (err) {
        scanStatus.textContent = err.message || "QR을 읽지 못했습니다. 위치를 조정해 다시 시도해주세요.";
      } finally {
        submitting = false;
      }
    });

    beginRobotGuide();
  }

  // ---------- 파손 신고 모달 ----------
  // 페이지에 모달용 DOM이 따로 없어서, 열 때 body에 붙였다가 닫으면 바로 제거하는 방식으로 처리한다.
  function openDamageReportModal(item, session) {
    const { escapeHtml } = window.LabBotItems;
    const { DAMAGE_SEVERITY_LABEL } = window.LabBotDamage;

    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card">
        <h3 class="modal-title">파손 신고 — ${escapeHtml(item.name)}</h3>
        <p class="modal-subtitle">사진을 올리면 제미나이 AI가 파손 정도를 자동으로 분석합니다.</p>

        <div class="modal-field">
          <label>파손 사진</label>
          <input type="file" accept="image/*" id="damagePhotoInput" />
          <img class="modal-preview" id="damagePhotoPreview" alt="미리보기" />
        </div>

        <div class="modal-field">
          <label>메모 (선택)</label>
          <textarea id="damageNoteInput" placeholder="예: 사용 중 렌즈에 금이 갔습니다"></textarea>
        </div>

        <p class="modal-status" id="damageModalStatus"></p>

        <div class="modal-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="close">취소</button>
          <button type="button" class="btn btn-primary btn-sm" data-action="submit">신고하기</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const photoInput = overlay.querySelector("#damagePhotoInput");
    const preview = overlay.querySelector("#damagePhotoPreview");
    const noteInput = overlay.querySelector("#damageNoteInput");
    const statusEl = overlay.querySelector("#damageModalStatus");
    const submitBtn = overlay.querySelector('[data-action="submit"]');
    const closeBtn = overlay.querySelector('[data-action="close"]');

    function close() {
      overlay.remove();
    }

    photoInput.addEventListener("change", () => {
      const file = photoInput.files[0];
      if (!file) {
        preview.style.display = "none";
        return;
      }
      preview.src = URL.createObjectURL(file);
      preview.style.display = "block";
    });

    closeBtn.addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(); // 배경 클릭으로도 닫히게
    });

    submitBtn.addEventListener("click", async () => {
      const file = photoInput.files[0];
      if (!file) {
        window.LabBotToast.error("파손 사진을 첨부해주세요.");
        return;
      }

      submitBtn.disabled = true;
      closeBtn.disabled = true;
      statusEl.textContent = "사진 업로드 중...";

      try {
        statusEl.textContent = "AI가 파손 정도를 분석하고 있습니다 (몇 초 정도 걸릴 수 있어요)...";
        const { assessment } = await window.LabBotDamage.submitDamageReport({
          item,
          session,
          file,
          note: noteInput.value.trim(),
        });

        if (assessment && assessment.error) {
          window.LabBotToast.info(`신고가 접수되었습니다.\nAI 분석은 실패했지만(${assessment.error}), 관리자가 사진을 직접 확인할 예정입니다.`);
        } else if (assessment && assessment.result) {
          const label = DAMAGE_SEVERITY_LABEL[assessment.result.severity] || assessment.result.severity;
          window.LabBotToast.success(`신고가 접수되었습니다.\nAI 판정: ${label} — ${assessment.result.summary}`);
        } else {
          window.LabBotToast.success("신고가 접수되었습니다.");
        }
        close();
      } catch (err) {
        statusEl.textContent = "";
        window.LabBotToast.error(err.message || "파손 신고에 실패했습니다.");
        submitBtn.disabled = false;
        closeBtn.disabled = false;
      }
    });
  }

  async function renderAll() {
    let loans;
    try {
      loans = await window.LabBotRentals.fetchMyLoans(session.id);
    } catch (err) {
      window.LabBotToast.error("대여 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const reserved = loans.filter((l) => l.status === "예약중");
    const active = loans.filter((l) => l.status === "대여중");
    const history = loans
      .filter((l) => l.status === "반납완료")
      .sort((a, b) => new Date(b.returned_at) - new Date(a.returned_at));

    statActiveCount.textContent = active.length;
    statTotalCount.textContent = loans.filter((l) => l.status !== "취소됨").length;  // 취소된 예약은 대여로 치지 않는다

    reservedListEl.innerHTML = "";
    reserved.forEach((loan) => reservedListEl.appendChild(renderReservedCard(loan)));
    reservedEmptyEl.style.display = reserved.length === 0 ? "block" : "none";

    activeListEl.innerHTML = "";
    active.forEach((loan) => activeListEl.appendChild(renderActiveCard(loan)));
    activeEmptyEl.style.display = active.length === 0 ? "block" : "none";

    // 물품 목록에서 예약하고 넘어온 경우 여기서 바로 안내창을 연다.
    // 목록이 그려진 뒤여야 해당 대여 건을 찾을 수 있다.
    openGuideFromQuery(loans);

    historyBodyEl.innerHTML = history
      .map(
        (loan) => `
        <tr>
          <td>${window.LabBotItems.escapeHtml(loan.items.name)}</td>
          <td>${formatDateTime(loan.borrowed_at)}</td>
          <td>${formatDateTime(loan.returned_at)}</td>
        </tr>
      `
      )
      .join("");
    historyEmptyEl.style.display = history.length === 0 ? "block" : "none";
  }

  // 우하단 ✉️ 버튼(inquiry-widget.js)으로 남긴 문의와 관리자 답변을 여기서 보여준다.
  async function renderInquiries() {
    let inquiries;
    try {
      inquiries = await window.LabBotInquiry.fetchMyInquiries(session.id);
    } catch (err) {
      window.LabBotToast.error("문의 내역을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const { escapeHtml } = window.LabBotItems;
    const { INQUIRY_STATUS_LABEL, INQUIRY_STATUS_BADGE_CLASS } = window.LabBotInquiry;

    inquiryEmptyEl.style.display = inquiries.length === 0 ? "block" : "none";

    const start = (inquiryPage - 1) * INQUIRY_PAGE_SIZE;
    const pageInquiries = inquiries.slice(start, start + INQUIRY_PAGE_SIZE);

    inquiryListEl.innerHTML = pageInquiries
      .map(
        (q) => `
        <article class="inquiry-card" data-inquiry-id="${q.id}">
          <div class="inquiry-card-header">
            <span class="badge ${INQUIRY_STATUS_BADGE_CLASS[q.status]}"><span class="badge-dot"></span>${INQUIRY_STATUS_LABEL[q.status]}</span>
            <h3 class="inquiry-card-subject">${escapeHtml(q.subject)}</h3>
            <span class="inquiry-card-date">${formatDateTime(q.created_at)}</span>
          </div>
          <p class="inquiry-card-message">${escapeHtml(q.message)}</p>
          ${q.admin_reply ? `<p class="inquiry-card-reply"><strong>답변</strong> · ${escapeHtml(q.admin_reply)}</p>` : ""}
          <div class="safety-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-action="delete-inquiry">삭제</button>
          </div>
        </article>
      `
      )
      .join("");

    inquiryListEl.querySelectorAll('[data-action="delete-inquiry"]').forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const card = e.currentTarget.closest("[data-inquiry-id]");
        const inquiryId = Number(card.dataset.inquiryId);
        if (!confirm("이 문의를 목록에서 삭제하시겠습니까?")) return;

        const target = e.currentTarget;
        target.disabled = true;
        try {
          await window.LabBotInquiry.hideMyInquiry(inquiryId);
          window.LabBotToast.success("문의를 삭제했습니다.");
          await renderInquiries();
        } catch (err) {
          window.LabBotToast.error("삭제에 실패했습니다: " + (err.message || err));
          target.disabled = false;
        }
      });
    });

    renderInquiryPagination(inquiries.length);
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
      renderInquiries();
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

  // 남은 시간을 "N시간 M분" 형태로 — 우선권(hold_expires_at) 마감까지 얼마나 남았는지 보여준다.
  function formatRemaining(isoString) {
    const diffMs = new Date(isoString) - new Date();
    if (diffMs <= 0) return "0분";
    const hours = Math.floor(diffMs / 3600000);
    const minutes = Math.floor((diffMs % 3600000) / 60000);
    return hours > 0 ? `${hours}시간 ${minutes}분` : `${minutes}분`;
  }

  // 품절 물품에 신청해둔 재입고 알림 목록 — items.html의 "재입고 알림 신청" 버튼으로
  // 만든 신청을 여기서도 보고 취소할 수 있게 한다(items.html까지 다시 찾아가지 않아도 됨).
  async function renderRestockSubscriptions() {
    if (!restockListEl || !window.LabBotRestock) return;

    let subs;
    try {
      subs = await window.LabBotRestock.fetchMySubscriptions(session.id);
    } catch (err) {
      window.LabBotToast.error("재입고 알림 신청 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const { escapeHtml } = window.LabBotItems;

    restockEmptyEl.style.display = subs.length === 0 ? "block" : "none";

    restockListEl.innerHTML = subs
      .map((s) => {
        const isHolding = s.hold_expires_at && new Date(s.hold_expires_at) > new Date();
        const statusHtml = isHolding
          ? `<span class="badge badge-st-needs_review"><span class="badge-dot"></span>지금 예약 가능 · ${formatRemaining(s.hold_expires_at)} 남음</span>`
          : `<span class="badge badge-pending"><span class="badge-dot"></span>대기 중</span>`;
        // 우선권을 쥔 동안(isHolding)에만 여기서 바로 예약할 수 있게 한다 — items.html까지
        // 다시 찾아가지 않아도 되도록. 아직 대기 중이면 재고가 없으니 예약 버튼 자체가
        // 의미없지만, 그렇다고 버튼을 아예 빼면 "신청 취소" 위치가 카드마다 들쭉날쭉해진다
        // (대기 중 카드는 버튼이 1개라 맨 왼쪽, 예약 가능 카드는 2번째 자리) — 그래서
        // 자리는 그대로 두고 안 보이게만 처리해서 취소 버튼이 항상 같은 위치에 오게 한다.
        const reserveBtnHtml = isHolding
          ? `<button type="button" class="btn btn-primary btn-sm" data-action="reserve-restock">${window.LabBotRentals.isConsumable(s.items) ? "사용하기" : "예약하기"}</button>`
          : `<button type="button" class="btn btn-primary btn-sm" style="visibility:hidden" tabindex="-1" aria-hidden="true" disabled>예약하기</button>`;
        return `
          <article class="inquiry-card" data-item-id="${s.item_id}">
            <div class="inquiry-card-header">
              ${statusHtml}
              <h3 class="inquiry-card-subject">${escapeHtml(s.items.name)}</h3>
            </div>
            <div class="safety-actions">
              ${reserveBtnHtml}
              <button type="button" class="btn btn-secondary btn-sm" data-action="cancel-restock">신청 취소</button>
            </div>
          </article>
        `;
      })
      .join("");

    restockListEl.querySelectorAll('[data-action="cancel-restock"]').forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const itemId = Number(e.currentTarget.closest("[data-item-id]").dataset.itemId);
        const target = e.currentTarget;
        target.disabled = true;
        try {
          await window.LabBotRestock.unsubscribeRestock(itemId, session.id);
          window.LabBotToast.info("알림 신청을 취소했습니다.");
          await renderRestockSubscriptions();
        } catch (err) {
          window.LabBotToast.error("취소에 실패했습니다: " + (err.message || err));
          target.disabled = false;
        }
      });
    });

    restockListEl.querySelectorAll('[data-action="reserve-restock"]').forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const sub = subs.find((s) => s.item_id === Number(e.currentTarget.closest("[data-item-id]").dataset.itemId));
        const target = e.currentTarget;
        target.disabled = true;
        try {
          const loan = await window.LabBotRentals.reserveItem(sub.items, session);
          window.LabBotToast.success(
            `"${sub.items.name}" 예약되었습니다. 로봇의 선반 안내 경로를 표시합니다.`
          );
          window.location.href = window.LabBotRentals.buildRobotGuideUrl(sub.items, loan);
        } catch (err) {
          window.LabBotToast.error(err.message || "처리 중 오류가 발생했습니다.");
          target.disabled = false;
        }
      });
    });
  }

  await renderAll();
  await renderInquiries();
  await renderRestockSubscriptions();
});
