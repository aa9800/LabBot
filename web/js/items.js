// LabBot - 물품목록 페이지 스크립트 (Supabase items 테이블 연동)
// TODO: "대여하기"/"반납하기" 클릭 시 AI 비전 확인 절차를 추가로 연결할 것

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

  function statusOf(item) {
    return item.available_qty > 0
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
        <span class="stock-count">재고 ${item.available_qty}/${item.total_qty}</span>
        <span class="badge badge-${status.key}"><span class="badge-dot"></span>${status.label}</span>
        <button type="button" class="btn ${status.buttonClass} btn-sm">${status.buttonLabel}</button>
      </div>
    `;

    row.querySelector("button").addEventListener("click", async (e) => {
      const button = e.currentTarget;
      button.disabled = true;

      try {
        const nextAvailable =
          status.key === "available" ? item.available_qty - 1 : item.available_qty + 1;

        await window.LabBotItems.updateItemStock(item.id, {
          available_qty: nextAvailable,
          total_qty: item.total_qty,
        });

        if (status.key === "available") {
          window.LabBotRentals.addRentalRecord(item, session);
        } else {
          window.LabBotRentals.returnRentalRecord(item.id);
        }

        await renderList();
      } catch (err) {
        alert(err.message || "처리 중 오류가 발생했습니다.");
        button.disabled = false;
      }
    });

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
