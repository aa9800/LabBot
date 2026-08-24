// LabBot - 물품목록 페이지 스크립트
// TODO: Supabase에서 물품 목록/재고 상태를 실시간으로 불러와 LAB_ITEMS를 대체할 것
// TODO: "대여하기"/"반납하기" 클릭 시 AI 비전 확인 절차를 추가로 연결할 것

document.addEventListener("DOMContentLoaded", () => {
  const listEl = document.getElementById("itemList");
  const searchInput = document.getElementById("itemSearch");
  const emptyState = document.getElementById("itemEmptyState");
  const filterButtons = document.querySelectorAll(".category-filter-btn");

  let activeCategory = "all";

  function statusOf(item) {
    return item.available > 0
      ? { key: "available", label: "대여가능", buttonLabel: "대여하기", buttonClass: "btn-primary" }
      : { key: "inuse", label: "대여중", buttonLabel: "반납하기", buttonClass: "btn-secondary" };
  }

  function renderRow(item) {
    const status = statusOf(item);
    const row = document.createElement("article");
    row.className = "item-row";
    row.dataset.category = item.category;

    row.innerHTML = `
      <div class="item-row-main">
        <span class="category-tag">${item.categoryLabel}</span>
        <h3 class="item-row-name">${item.name}</h3>
        <span class="item-row-location">${item.location}</span>
      </div>
      <div class="item-row-meta">
        <span class="stock-count">재고 ${item.available}/${item.total}</span>
        <span class="badge badge-${status.key}"><span class="badge-dot"></span>${status.label}</span>
        <button type="button" class="btn ${status.buttonClass} btn-sm">${status.buttonLabel}</button>
      </div>
    `;

    row.querySelector("button").addEventListener("click", async () => {
      const session = await window.LabBotAuth.requireLogin("items.html");
      if (!session) return;

      if (status.key === "available") {
        item.available -= 1;
        window.LabBotRentals.addRentalRecord(item, session);
      } else {
        item.available += 1;
        window.LabBotRentals.returnRentalRecord(item.id);
      }

      saveLabItems(LAB_ITEMS);
      renderList();
    });

    return row;
  }

  function renderList() {
    const query = searchInput.value.trim().toLowerCase();

    const filtered = LAB_ITEMS.filter((item) => {
      const matchesCategory = activeCategory === "all" || item.category === activeCategory;
      const matchesQuery = item.name.toLowerCase().includes(query);
      return matchesCategory && matchesQuery;
    });

    listEl.innerHTML = "";
    filtered.forEach((item) => listEl.appendChild(renderRow(item)));

    emptyState.style.display = filtered.length === 0 ? "block" : "none";
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

  renderList();
});
