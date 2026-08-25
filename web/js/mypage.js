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

    card.querySelector("[data-return-loan]").addEventListener("click", async (e) => {
      const button = e.currentTarget;
      button.disabled = true;

      try {
        await window.LabBotRentals.returnLoan(loan.id);
        await renderAll();
      } catch (err) {
        alert(err.message || "반납 처리에 실패했습니다.");
        button.disabled = false;
      }
    });

    card.querySelector("[data-report-damage]").addEventListener("click", () => {
      openDamageReportModal(item, session);
    });

    return card;
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
        alert("파손 사진을 첨부해주세요.");
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
          alert(`신고가 접수되었습니다.\nAI 분석은 실패했지만(${assessment.error}), 관리자가 사진을 직접 확인할 예정입니다.`);
        } else if (assessment && assessment.result) {
          const label = DAMAGE_SEVERITY_LABEL[assessment.result.severity] || assessment.result.severity;
          alert(`신고가 접수되었습니다.\n\nAI 판정: ${label}\n${assessment.result.summary}`);
        } else {
          alert("신고가 접수되었습니다.");
        }
        close();
      } catch (err) {
        statusEl.textContent = "";
        alert(err.message || "파손 신고에 실패했습니다.");
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
      alert("대여 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    const active = loans.filter((l) => l.status === "대여중");
    const history = loans
      .filter((l) => l.status === "반납완료")
      .sort((a, b) => new Date(b.returned_at) - new Date(a.returned_at));

    statActiveCount.textContent = active.length;
    statTotalCount.textContent = loans.length;

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
