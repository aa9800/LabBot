// LabBot - 물품목록 페이지 스크립트 (Supabase items 테이블 연동)
// TODO: "대여하기" 클릭 시 AI 비전 확인 절차를 추가로 연결할 것
// 반납은 개별 대여 건(loans) 단위라 여기가 아니라 mypage.html "내 대여 목록"에서 처리한다.

document.addEventListener("DOMContentLoaded", async () => {
  const session = await window.LabBotAuth.requireLogin("items.html");
  if (!session) return;

  const listEl = document.getElementById("itemList");
  const searchInput = document.getElementById("itemSearch");
  const locationSelect = document.getElementById("itemLocationFilter");
  const emptyState = document.getElementById("itemEmptyState");
  const filterButtons = document.querySelectorAll(".category-filter-btn");

  let activeCategory = "all";
  let activeLocation = "all";

  function renderRow(item) {
    // 재고상태는 items-data.js의 computeStockStatus() 한 곳에서만 계산한다 —
    // 여기서 available_qty만 보고 다시 판단하지 않는다(유효기간/점검중 케이스를 놓치게 됨).
    const { escapeHtml, STOCK_STATUS_FULL_LABEL, STOCK_STATUS_BADGE_CLASS, computeStockStatus, canRentItem } =
      window.LabBotItems;
    const statusKey = computeStockStatus(item);
    const statusLabel = STOCK_STATUS_FULL_LABEL[statusKey];
    const badgeClass = STOCK_STATUS_BADGE_CLASS[statusKey];
    const rentable = canRentItem(item);

    const row = document.createElement("article");
    row.className = "item-row";
    row.dataset.category = item.category;

    const actionHtml = rentable
      ? `<button type="button" class="btn btn-primary btn-sm">대여하기</button>`
      : `<button type="button" class="btn btn-secondary btn-sm" disabled>대여불가</button>`;

    const expiresHtml = item.expires_at
      ? `<span class="item-row-location">유효기간 ${escapeHtml(item.expires_at)}</span>`
      : "";

    row.innerHTML = `
      <div class="item-row-main">
        <span class="category-tag">${escapeHtml(item.categoryLabel)}</span>
        <h3 class="item-row-name">${escapeHtml(item.name)}</h3>
        <span class="item-row-location">${escapeHtml(item.location)} · ${escapeHtml(item.storage_condition || "-")}</span>
        ${expiresHtml}
      </div>
      <div class="item-row-meta">
        <span class="stock-count">재고 ${item.available_qty}/${item.total_qty} ${escapeHtml(item.unit || "")}</span>
        <span class="badge ${badgeClass}"><span class="badge-dot"></span>${statusLabel}</span>
        ${actionHtml}
      </div>
    `;

    const button = row.querySelector("button");
    if (rentable) {
      button.addEventListener("click", async (e) => {
        const target = e.currentTarget;
        target.disabled = true;

        try {
          const loan = await window.LabBotRentals.createLoan(item, session);
          const dueDate = new Date(loan.due_at).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
          alert(`"${item.name}" 대여가 완료되었습니다.\n반납 예정일: ${dueDate}\n마이페이지에서 확인할 수 있습니다.`);
          await renderList();
        } catch (err) {
          alert(err.message || "대여 처리 중 오류가 발생했습니다.");
          target.disabled = false;
        }
      });
    }

    return row;
  }

  async function populateLocationOptions() {
    const locations = await window.LabBotItems.fetchLocations();
    const current = locationSelect.value;

    locationSelect.innerHTML =
      `<option value="all">전체 위치</option>` +
      locations.map((loc) => `<option value="${loc}">${loc}</option>`).join("");

    if ([...locationSelect.options].some((o) => o.value === current)) {
      locationSelect.value = current;
    }
  }

  async function renderList() {
    let items;
    try {
      items = await window.LabBotItems.searchItems({
        name: searchInput.value,
        category: activeCategory,
        location: activeLocation,
      });
    } catch (err) {
      alert("물품 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    listEl.innerHTML = "";
    items.forEach((item) => listEl.appendChild(renderRow(item)));

    emptyState.style.display = items.length === 0 ? "block" : "none";
  }

  filterButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeCategory = btn.dataset.category;
      renderList();
    });
  });

  searchInput.addEventListener("input", renderList);
  locationSelect.addEventListener("change", () => {
    activeLocation = locationSelect.value;
    renderList();
  });

  await populateLocationOptions();
  await renderList();
});
