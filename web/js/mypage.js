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

    return card;
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
