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
  const paginationEl = document.getElementById("itemPagination");

  let activeCategory = "all";
  let activeLocation = "all";

  // 물품이 60개가 넘어가면 페이지 전체가 한없이 길어져서, 화면 단위로 나눠 보여준다.
  // 검색/필터가 바뀌면 결과가 달라지니 1페이지로 되돌린다(renderList에서 처리).
  const PAGE_SIZE = 12;
  let currentPage = 1;

  function renderRow(item) {
    // 재고상태는 items-data.js의 computeStockStatus() 한 곳에서만 계산한다 —
    // 여기서 available_qty만 보고 다시 판단하지 않는다(유효기간/점검중 케이스를 놓치게 됨).
    const { escapeHtml, STOCK_STATUS_FULL_LABEL, STOCK_STATUS_BADGE_CLASS, computeStockStatus, canRentItem, categoryIconOf } =
      window.LabBotItems;
    const statusKey = computeStockStatus(item);
    const statusLabel = STOCK_STATUS_FULL_LABEL[statusKey];
    const badgeClass = STOCK_STATUS_BADGE_CLASS[statusKey];
    const rentable = canRentItem(item);
    const consumable = window.LabBotRentals.isConsumable(item);
    const actionLabel = consumable ? "사용하기" : "대여하기";

    const row = document.createElement("article");
    row.className = "item-row";
    row.dataset.category = item.category;

    const actionHtml = rentable
      ? `<button type="button" class="btn btn-primary btn-sm">${actionLabel}</button>`
      : `<button type="button" class="btn btn-secondary btn-sm" disabled>${consumable ? "재고없음" : "대여불가"}</button>`;

    const expiresHtml = item.expires_at
      ? `<span class="item-row-location">유효기간 ${escapeHtml(item.expires_at)}</span>`
      : "";

    row.innerHTML = `
      <div class="item-row-icon" aria-hidden="true">${categoryIconOf(item.category)}</div>
      <div class="item-row-main"${item.notes ? ` title="${escapeHtml(item.notes)}"` : ""}>
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
          if (consumable) {
            await window.LabBotRentals.consumeItem(item, session);
            alert(`"${item.name}" 사용 처리되었습니다.`);
          } else {
            const loan = await window.LabBotRentals.createLoan(item, session);
            const dueDate = new Date(loan.due_at).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
            alert(`"${item.name}" 대여가 완료되었습니다.\n반납 예정일: ${dueDate}\n마이페이지에서 확인할 수 있습니다.`);
          }
          await renderList();
        } catch (err) {
          alert(err.message || "처리 중 오류가 발생했습니다.");
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

  function renderPagination(totalItems) {
    const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;

    if (totalPages <= 1) {
      paginationEl.innerHTML = "";
      return;
    }

    const goTo = (page) => {
      currentPage = page;
      renderList();
      listEl.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    paginationEl.innerHTML = `
      <button type="button" class="btn btn-secondary btn-sm" data-page-action="prev" ${currentPage === 1 ? "disabled" : ""}>이전</button>
      <span class="pagination-status mono">${currentPage} / ${totalPages}</span>
      <button type="button" class="btn btn-secondary btn-sm" data-page-action="next" ${currentPage === totalPages ? "disabled" : ""}>다음</button>
    `;
    paginationEl.querySelector('[data-page-action="prev"]').addEventListener("click", () => goTo(currentPage - 1));
    paginationEl.querySelector('[data-page-action="next"]').addEventListener("click", () => goTo(currentPage + 1));
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

    const start = (currentPage - 1) * PAGE_SIZE;
    const pageItems = items.slice(start, start + PAGE_SIZE);

    listEl.innerHTML = "";
    pageItems.forEach((item) => listEl.appendChild(renderRow(item)));

    emptyState.style.display = items.length === 0 ? "block" : "none";
    renderPagination(items.length);
  }

  function renderListFromStart() {
    currentPage = 1; // 검색/필터가 바뀌면 이전 페이지 번호가 의미없어지니 1페이지로
    renderList();
  }

  filterButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeCategory = btn.dataset.category;
      renderListFromStart();
    });
  });

  // 한 글자 입력할 때마다 Supabase에 요청을 보내면 낭비니, 타이핑이 잠깐 멈췄을 때만 검색한다.
  let searchDebounceTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(renderListFromStart, 300);
  });
  locationSelect.addEventListener("change", () => {
    activeLocation = locationSelect.value;
    renderListFromStart();
  });

  await populateLocationOptions();
  await renderList();
});
