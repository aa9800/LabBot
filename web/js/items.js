// LabBot - 물품목록 페이지 스크립트 (Supabase items 테이블 연동)
// "대여하기"를 눌러도 여기서 바로 대여가 끝나지 않는다 — 예약(reserveItem)만 되고,
// 실제 수령 확인(로봇 안내 + QR 스캔)은 마이페이지에서 진행한다(rentals.js 상단 설명 참고).
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

  // 품절 물품에 신청해둔 재입고 알림 상태(item_id 집합) — 매번 물품마다 따로 조회하면
  // N+1이 되니 한 번만 불러와서 renderRow에서 함께 쓰고, 신청/취소할 때 그 자리에서
  // 갱신한다(다시 통째로 불러오지 않음). 실제 알림 전송/소비는 nav.js가 담당.
  let subscribedItemIds = new Set();

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
    // 소모품은 그 자리에서 바로 "사용"되지만, 장비/PPE 등은 예약만 되고 실제 수령은
    // 마이페이지에서 로봇 안내 + QR 스캔을 거쳐야 확정된다.
    const actionLabel = consumable ? "사용하기" : "예약하기";

    const row = document.createElement("article");
    row.className = "item-row";
    row.dataset.category = item.category;

    // 품절(OUT_OF_STOCK)일 때만 재입고 알림 신청 버튼을 보여준다 — 점검중/유효기간
    // 만료는 재고가 다시 들어온다고 해결되는 문제가 아니라서 대상에서 뺀다.
    const isSubscribed = subscribedItemIds.has(item.id);
    let actionHtml;
    if (rentable) {
      actionHtml = `<button type="button" class="btn btn-primary btn-sm">${actionLabel}</button>`;
    } else if (statusKey === "OUT_OF_STOCK") {
      actionHtml = `<button type="button" class="btn btn-secondary btn-sm${isSubscribed ? " is-subscribed" : ""}" data-action="restock" data-subscribed="${isSubscribed}">${isSubscribed ? "알림 신청됨" : "재입고 알림"}</button>`;
    } else {
      actionHtml = `<button type="button" class="btn btn-secondary btn-sm" disabled>${consumable ? "재고없음" : "대여불가"}</button>`;
    }

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
        <div style="display:flex; gap:0.35rem; align-items:center;">
          ${actionHtml}
          <a href="lab-twin.html?findItem=${item.id}" class="btn btn-secondary btn-sm" title="가상 실험실 2.5D 위치 찾기">위치</a>
        </div>
      </div>
    `;

    const button = row.querySelector("button");
    if (rentable) {
      button.addEventListener("click", async (e) => {
        const target = e.currentTarget;
        target.disabled = true;

        try {
          // 소모품도 이제 그 자리에서 바로 처리되지 않는다 — 예약만 되고, 마이페이지에서
          // 수량을 입력하고 QR을 스캔해야만 실제 사용으로 확정된다(장비 대여와 동일한 원칙).
          await window.LabBotRentals.reserveItem(item, session);
          window.LabBotToast.success(
            `"${item.name}" 예약되었습니다. 마이페이지에서 로봇 안내를 받아 ${consumable ? "사용" : "수령"}하세요.`
          );
          window.location.href = "mypage.html";
        } catch (err) {
          window.LabBotToast.error(err.message || "처리 중 오류가 발생했습니다.");
          target.disabled = false;
        }
      });
    } else if (statusKey === "OUT_OF_STOCK") {
      button.addEventListener("click", async (e) => {
        const target = e.currentTarget;
        const subscribed = target.dataset.subscribed === "true";
        target.disabled = true;

        try {
          if (subscribed) {
            await window.LabBotRestock.unsubscribeRestock(item.id, session.id);
            subscribedItemIds.delete(item.id);
            target.dataset.subscribed = "false";
            target.textContent = "재입고 알림";
            target.classList.remove("is-subscribed");
            window.LabBotToast.info("알림 신청을 취소했습니다.");
          } else {
            await window.LabBotRestock.subscribeRestock(item.id, session.id);
            subscribedItemIds.add(item.id);
            target.dataset.subscribed = "true";
            target.textContent = "알림 신청됨";
            target.classList.add("is-subscribed");
            window.LabBotToast.success("재입고되면 알려드릴게요.");
          }
        } catch (err) {
          window.LabBotToast.error(err.message || "처리 중 오류가 발생했습니다.");
        } finally {
          target.disabled = false;
        }
      });
    }

    return row;
  }

  // 검색/필터 결과를 불러오는 동안 빈 화면 대신 자리표시자 카드를 보여준다.
  function renderSkeleton() {
    listEl.innerHTML = Array.from({ length: 6 })
      .map(
        () => `
        <article class="item-row skeleton-row">
          <div class="item-row-icon"><span class="skeleton-bar" style="width:20px;height:20px;border-radius:50%;"></span></div>
          <div class="item-row-main">
            <span class="skeleton-bar" style="width:56px;height:10px;margin-bottom:8px;"></span>
            <span class="skeleton-bar" style="width:150px;height:14px;margin-bottom:8px;"></span>
            <span class="skeleton-bar" style="width:110px;height:10px;"></span>
          </div>
          <div class="item-row-meta">
            <span class="skeleton-bar" style="width:80px;height:10px;margin-bottom:8px;"></span>
            <span class="skeleton-bar" style="width:72px;height:26px;"></span>
          </div>
        </article>
      `
      )
      .join("");
    emptyState.style.display = "none";
  }

  async function populateLocationOptions() {
    const locations = await window.LabBotItems.fetchLocations();
    const current = locationSelect.value;

    locationSelect.innerHTML =
      `<option value="all">전체 위치</option>` +
      locations.map((loc) => `<option value="${escapeHtml(loc)}">${escapeHtml(loc)}</option>`).join("");

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
    renderSkeleton();

    let items;
    try {
      items = await window.LabBotItems.searchItems({
        name: searchInput.value,
        category: activeCategory,
        location: activeLocation,
      });
    } catch (err) {
      window.LabBotToast.error("물품 목록을 불러오지 못했습니다: " + (err.message || err));
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

  try {
    subscribedItemIds = await window.LabBotRestock.fetchMySubscribedItemIds(session.id);
  } catch (err) {
    console.warn("LabBot: 재입고 알림 신청 목록을 불러오지 못했습니다", err);
  }

  await populateLocationOptions();
  await renderList();
});
