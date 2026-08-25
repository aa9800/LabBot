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
            <div class="scan-line"></div>
            <p class="guide-eyebrow">${copy.eyebrow} · 로봇 안내</p>
            <h3 class="guide-message">${copy.message}</h3>
            <p class="guide-caption">표시된 위치로 이동한 뒤 물품 QR로 확인하세요</p>
          </div>
          <p class="guide-item-name">${escapeHtml(item.name)} · ${escapeHtml(item.location)}${
            mode === "use" ? ` · ${qty}${escapeHtml(item.unit || "개")}` : ""
          }</p>
          <!-- 실제 로봇 내비게이션은 아직 연결 전이라(발표 자료에서 시뮬레이션 검증 단계로 표시),
               여기서도 실시간 추적처럼 보이지 않도록 안내 화면임을 명시한다(GPT 리뷰 지적). -->
          <p class="guide-sim-note mono">안내 화면 · 실제 위치는 QR로 최종 확인됩니다</p>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-action="cancel">취소</button>
            <button type="button" class="btn btn-primary btn-sm" data-action="to-scan">도착했어요 · QR 스캔하기</button>
          </div>
        </div>

        <div class="guide-step" data-step="scan" hidden>
          <p class="guide-eyebrow">QR 스캔</p>
          <p class="guide-caption">${escapeHtml(item.name)}에 붙은 QR 코드를 카메라에 비춰주세요</p>
          <div class="qr-scan-frame">
            <video class="qr-scan-video" id="guideVideo" playsinline muted></video>
            <div class="qr-scan-reticle"></div>
          </div>
          <p class="guide-scan-status" id="guideScanStatus"></p>
          <div class="guide-manual-fallback">
            <label for="guideManualInput">카메라가 안 되면 QR 코드를 직접 입력하세요</label>
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

    let stream = null;
    let rafId = null;
    let submitting = false;
    let closed = false;

    function showStep(name) {
      overlay.querySelectorAll("[data-step]").forEach((el) => {
        el.hidden = el.dataset.step !== name;
      });
    }

    function stopCamera() {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = null;
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
      }
    }

    function close() {
      if (closed) return;
      closed = true;
      stopCamera();
      overlay.remove();
    }

    overlay.querySelectorAll('[data-action="cancel"]').forEach((btn) => btn.addEventListener("click", close));
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(); // 배경 클릭으로도 닫히게(진행 중인 예약/대여는 그대로 유지됨)
    });

    const scanStatus = overlay.querySelector("#guideScanStatus");
    const manualInput = overlay.querySelector("#guideManualInput");

    async function submitCode(code) {
      scanStatus.textContent = "확인 중...";
      try {
        if (mode === "pickup") {
          await window.LabBotRentals.confirmPickup(loan.id, code);
        } else if (mode === "return") {
          await window.LabBotRentals.confirmReturn(loan.id, code);
        } else {
          await window.LabBotRentals.confirmUsage(loan.id, code, qty);
        }
        stopCamera();

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
        scanStatus.textContent = err.message || "확인에 실패했습니다. 다시 스캔해주세요.";
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
      const video = overlay.querySelector("#guideVideo");

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        scanStatus.textContent = "이 브라우저는 카메라를 지원하지 않습니다 — 아래에 QR 코드를 직접 입력해주세요.";
        return;
      }

      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      } catch (err) {
        scanStatus.textContent = "카메라를 사용할 수 없습니다 — 아래에 QR 코드를 직접 입력해주세요.";
        return;
      }

      video.srcObject = stream;
      await video.play();

      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");

      function tick() {
        if (closed) return;
        if (!submitting && video.readyState === video.HAVE_ENOUGH_DATA) {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const code = window.jsQR(imageData.data, imageData.width, imageData.height);
          if (code && code.data) {
            submitting = true;
            submitCode(code.data).finally(() => {
              submitting = false;
            });
          }
        }
        rafId = requestAnimationFrame(tick);
      }
      rafId = requestAnimationFrame(tick);
    });
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
    statTotalCount.textContent = loans.length;

    reservedListEl.innerHTML = "";
    reserved.forEach((loan) => reservedListEl.appendChild(renderReservedCard(loan)));
    reservedEmptyEl.style.display = reserved.length === 0 ? "block" : "none";

    activeListEl.innerHTML = "";
    active.forEach((loan) => activeListEl.appendChild(renderActiveCard(loan)));
    activeEmptyEl.style.display = active.length === 0 ? "block" : "none";

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

  await renderAll();
});
