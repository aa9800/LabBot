// LabBot - 2.5D 가상 생명공학 실험실 디지털 트윈 컨트롤러
// Supabase items, loans 실시간 연동 및 가상 픽업/반납 인터랙션

(function () {
  let _itemsMap = new Map(); // itemId or name -> item object
  let _sceneBindings = new Map(); // sceneObjectId -> DB가 승인한 item_id 바인딩
  let _currentFilterRoom = "all";
  let _selectedVirtualObj = null;
  let _matchedItem = null;
  let _activeUserLoans = [];
  let _routeActive = false;

  // SVG 아이콘 세트
  const SVG_ICONS = {
    pipette: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 2l4 4-2.5 2.5-4-4L18 2zM15.5 4.5l-11 11V19h3.5l11-11-3.5-3.5zM2 22l3-1"/></svg>`,
    tips: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="6" width="16" height="14" rx="2"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M8 11h8M8 15h8"/></svg>`,
    centrifuge: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M12 3v5M12 16v5M3 12h5M16 12h5"/></svg>`,
    scale: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v18M6 8l6-2 6 2M6 8L3 14h6L6 8zM18 8l-3 6h6l-3-6z"/></svg>`,
    phmeter: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="6" y="2" width="12" height="12" rx="2"/><path d="M12 14v8M10 22h4M9 6h6M9 9h3"/></svg>`,
    microscope: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 18h12M10 22h4M12 18V9M9 9l3-7 3 7M6 14h6"/></svg>`,
    pcr: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8" cy="10" r="1.5"/><circle cx="12" cy="10" r="1.5"/><circle cx="16" cy="10" r="1.5"/><path d="M7 15h10"/></svg>`,
    freezer: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="2" width="14" height="20" rx="2"/><path d="M5 10h14M16 6v2M16 14v3"/></svg>`,
    reagent: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 2h6M10 2v5l-4 8a3 3 0 0 0 2.6 4.5h8.8a3 3 0 0 0 2.6-4.5l-4-8V2"/></svg>`,
    safety: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V5l7-3zM12 8v5M12 16h.01"/></svg>`,
    waste: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18M8 6V4h8v2M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6"/></svg>`
  };

  async function initVirtualLab() {
    renderRoomTabs();
    await loadDbItems();
    await loadUserLoans();
    renderLabCanvas();
    setupEventListeners();
    subscribeRealtime();

    // URL 파라미터 확인 (?findItem=12 or ?room=기기실-1)
    const urlParams = new URLSearchParams(window.location.search);
    const targetItemId = urlParams.get("findItem");
    const targetRoom = urlParams.get("room");

    if (targetRoom) {
      filterByRoom(targetRoom);
    }
    if (targetItemId) {
      focusItemById(parseInt(targetItemId, 10));
    }
  }

  // 1. 구역 탭 렌더링
  function renderRoomTabs() {
    const tabsContainer = document.getElementById("roomTabsContainer");
    if (!tabsContainer) return;

    tabsContainer.innerHTML = VIRTUAL_LAB_ROOMS.map(
      (room) => `
      <button class="room-tab-btn ${room.id === _currentFilterRoom ? "active" : ""}" data-room-id="${room.id}">
        ${room.name}
      </button>
    `
    ).join("");

    tabsContainer.querySelectorAll(".room-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const roomId = btn.getAttribute("data-room-id");
        filterByRoom(roomId);
      });
    });
  }

  // 2. Supabase items 테이블 데이터 로드
  async function loadDbItems() {
    try {
      const { data, error } = await supabaseClient
        .from("items")
        .select("*")
        .order("name", { ascending: true });

      if (error) throw error;

      _itemsMap.clear();
      (data || []).forEach((item) => {
        _itemsMap.set(item.id, item);
        _itemsMap.set(item.name, item);
      });

      const { data: bindings, error: bindingError } = await supabaseClient
        .from("virtual_lab_objects")
        .select("scene_object_id, item_id, room, display_mode")
        .eq("enabled", true);
      if (bindingError) {
        console.warn("[VirtualLab] virtual_lab_objects migration is not applied yet:", bindingError);
        _sceneBindings.clear();
      } else {
        _sceneBindings = new Map((bindings || []).map((row) => [row.scene_object_id, row]));
      }

      console.log(`[VirtualLab] Supabase items loaded: ${data ? data.length : 0} items`);
    } catch (err) {
      console.error("[VirtualLab] Failed to load DB items:", err);
      if (window.LabBotToast) {
        LabBotToast.show("물품 데이터를 불러오는 중 오류가 발생했습니다.", "error");
      }
    }
  }

  // 3. 사용자 대여/예약 내역 로드
  async function loadUserLoans() {
    if (!window.LabBotAuth) return;
    const session = await LabBotAuth.currentSession();
    if (!session) return;

    try {
      const { data, error } = await supabaseClient
        .from("loans")
        .select("*, items(id, name, category, location, item_type, available_qty, total_qty, unit)")
        .eq("user_id", session.id)
        .in("status", ["예약중", "대여중"]);

      if (error) throw error;
      _activeUserLoans = data || [];
    } catch (err) {
      console.warn("[VirtualLab] Failed to fetch active loans:", err);
    }
  }

  // 가상 객체와 실제 DB item 매칭
  function findMatchingItem(vObj) {
    const binding = _sceneBindings.get(vObj.sceneObjectId);
    if (binding && _itemsMap.has(binding.item_id)) {
      return _itemsMap.get(binding.item_id);
    }
    if (vObj.itemId && _itemsMap.has(vObj.itemId)) {
      return _itemsMap.get(vObj.itemId);
    }
    // itemQuery 기반 매칭 (부분 일치)
    if (vObj.itemQuery) {
      for (const [key, val] of _itemsMap.entries()) {
        if (typeof key === "string" && key.toLowerCase().includes(vObj.itemQuery.toLowerCase())) {
          return val;
        }
      }
    }
    return null;
  }

  // 4. 2.5D 가상 실험실 캔버스 렌더링
  function renderLabCanvas() {
    const canvas = document.getElementById("labCanvas");
    if (!canvas) return;

    // 환경 객체 렌더링
    let envHtml = VIRTUAL_LAB_ENVIRONMENT_PROPS.map((env) => {
      const style = `left:${env.position.x}%; top:${env.position.y}%; width:${env.width}%; height:${env.height}%;`;
      let cls = "env-workbench";
      if (env.type === "glass_wall") cls = "env-glass-wall";
      if (env.type === "safety_cabinet") cls = "env-safety-cabinet";
      if (env.type === "fume_hood") cls = "env-workbench";
      if (env.type === "clean_bench") cls = "env-workbench";

      return `<div class="env-prop ${cls}" style="${style}">
        ${env.name}
      </div>`;
    }).join("");

    // 디지털 트윈 물품 노드 렌더링
    let nodesHtml = VIRTUAL_LAB_OBJECTS.map((vObj) => {
      const matched = findMatchingItem(vObj);
      const isVisible = _currentFilterRoom === "all" || vObj.room === _currentFilterRoom;
      if (!isVisible) return "";

      // 재고 상태 계산 (DB 연동)
      // 뷰포트는 라이트/다크 모드와 무관하게 항상 다크 모드로 고정되므로, 여기 색상도
      // 테마 변수(var(--accent) 등) 대신 다크 모드 값을 그대로 박아둔다.
      let stockStatus = "AVAILABLE";
      let statusColor = "#00d992"; // 사이트 강조색과 동일한 초록(다크 모드 값 고정)

      if (matched) {
        stockStatus = computeStockStatus(matched);
        if (stockStatus === "OUT_OF_STOCK" || stockStatus === "EXPIRED") {
          statusColor = "#f87171";
        } else if (stockStatus === "LOW_STOCK" || stockStatus === "EXPIRING_SOON") {
          statusColor = "#fbbf24";
        } else if (stockStatus === "MAINTENANCE") {
          statusColor = "#8b949e"; // 점검중은 다른 페이지의 badge-inuse와 같은 중립색
        }
      }

      const itemName = matched ? matched.name : vObj.displayNameFallback;
      const iconSvg = SVG_ICONS[vObj.iconType] || SVG_ICONS.pipette;
      const isSelected = _selectedVirtualObj && _selectedVirtualObj.sceneObjectId === vObj.sceneObjectId;

      return `
        <div class="lab-item-node ${isSelected ? "highlighted" : ""}" 
             id="node-${vObj.sceneObjectId}"
             style="left: ${vObj.position.x}%; top: ${vObj.position.y}%;"
             data-obj-id="${vObj.sceneObjectId}">
          <div class="node-box" style="border-color: ${isSelected ? "#2fd6a1" : statusColor}">
            <span class="node-code-badge">${vObj.label}</span>
            ${iconSvg}
            <span class="node-status-dot" style="background: ${statusColor}"></span>
          </div>
          <div class="node-title-label">${itemName}</div>
        </div>
      `;
    }).join("");

    // Yahboom Raspbot 로봇 마커
    const robotHtml = `
      <div class="raspbot-marker" id="raspbotMarker" style="left: 48%; top: 68%;">
        <div class="raspbot-body">
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="6" width="18" height="12" rx="3"/>
            <circle cx="8" cy="18" r="2.5"/><circle cx="16" cy="18" r="2.5"/>
            <circle cx="12" cy="11" r="2.5"/><path d="M12 6V3"/>
          </svg>
        </div>
        <span class="raspbot-label">Raspbot #1</span>
      </div>
    `;

    canvas.innerHTML = `
      <div class="lab-floor-grid"></div>
      <svg class="lab-robot-track-svg">
        <path class="robot-track-line ${_routeActive ? "robot-guide-active" : ""}" 
              d="M 120 420 L 320 420 L 580 420 L 780 420 L 780 280 L 520 280 L 220 280 L 220 420 Z" />
      </svg>
      ${envHtml}
      ${nodesHtml}
      ${robotHtml}
    `;

    // 노드 클릭 이벤트 바인딩
    canvas.querySelectorAll(".lab-item-node").forEach((el) => {
      el.addEventListener("click", () => {
        const objId = el.getAttribute("data-obj-id");
        selectObjectById(objId);
      });
    });
  }

  // 5. 물체 선택 및 사이드 인스펙터 패널 갱신
  function selectObjectById(sceneObjectId) {
    const vObj = VIRTUAL_LAB_OBJECTS.find((o) => o.sceneObjectId === sceneObjectId);
    if (!vObj) return;

    _selectedVirtualObj = vObj;
    _matchedItem = findMatchingItem(vObj);

    renderLabCanvas();
    updateInspectorPanel();
  }

  function updateInspectorPanel() {
    const titleEl = document.getElementById("inspectTitle");
    const roomEl = document.getElementById("inspectRoom");
    const categoryEl = document.getElementById("inspectCategory");
    const stockEl = document.getElementById("inspectStock");
    const statusEl = document.getElementById("inspectStatus");
    const storageEl = document.getElementById("inspectStorage");
    const expiresEl = document.getElementById("inspectExpires");
    const descEl = document.getElementById("inspectDesc");
    const actionsEl = document.getElementById("inspectActions");

    if (!_selectedVirtualObj) return;

    const matched = _matchedItem;
    const itemName = matched ? matched.name : _selectedVirtualObj.displayNameFallback;
    const category = matched ? matched.category : _selectedVirtualObj.category;
    const room = matched ? matched.location : _selectedVirtualObj.room;
    const stockStr = matched ? `${matched.available_qty} / ${matched.total_qty} ${matched.unit || "개"}` : "DB 조회 중";
    const statusKey = matched ? computeStockStatus(matched) : "AVAILABLE";
    const statusLabel = STOCK_STATUS_LABEL[statusKey] || statusKey;
    const storage = matched ? (matched.storage_condition || "실온") : "실온";
    const expires = matched ? (matched.expires_at || "해당 없음") : "해당 없음";

    if (titleEl) titleEl.innerText = `${_selectedVirtualObj.label}: ${itemName}`;
    if (roomEl) roomEl.innerText = `${room} (${_selectedVirtualObj.zoneTag})`;
    if (categoryEl) categoryEl.innerText = category;
    if (stockEl) stockEl.innerText = stockStr;
    if (statusEl) statusEl.innerText = statusLabel;
    if (storageEl) storageEl.innerText = storage;
    if (expiresEl) expiresEl.innerText = expires;
    if (descEl) descEl.innerText = _selectedVirtualObj.description;

    // 해당 물품에 대한 사용자 예약 건이 있는지 확인
    const userReservation = matched ? _activeUserLoans.find((l) => l.item_id === matched.id && l.status === "예약중") : null;
    const userActiveLoan = matched ? _activeUserLoans.find((l) => l.item_id === matched.id && l.status === "대여중") : null;
    const isConsumable = matched && window.LabBotRentals && window.LabBotRentals.isConsumable(matched);

    let actionBtnsHtml = "";

    if (userReservation) {
      actionBtnsHtml += `
        <button class="btn-virtual-action btn-virtual-scan" id="btnVirtualPickup">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/></svg>
          ${isConsumable ? "가상 QR 사용 스캔" : "가상 QR 픽업 스캔 (수령 확정)"}
        </button>
      `;
    } else if (userActiveLoan) {
      actionBtnsHtml += `
        <button class="btn-virtual-action btn-virtual-scan" id="btnVirtualReturn">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 14l-4-4 4-4M5 10h11a4 4 0 1 1 0 8h-1"/></svg>
          가상 QR 반납 스캔
        </button>
      `;
    } else if (matched && matched.available_qty > 0 && statusKey !== "MAINTENANCE" && statusKey !== "EXPIRED") {
      actionBtnsHtml += `
        <button class="btn-virtual-action btn-virtual-reserve" id="btnVirtualReserve">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
          이 물품 예약하기
        </button>
      `;
    } else {
      actionBtnsHtml += `
        <button class="btn-virtual-action" style="background:var(--surface-2); color:var(--text-faint); cursor:not-allowed;" disabled>
          현재 대여/사용 불가
        </button>
      `;
    }

    actionBtnsHtml += `
      <button class="btn-virtual-action btn-virtual-route" id="btnGuideRoute">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        로봇 이동 경로 안내
      </button>
    `;

    if (actionsEl) {
      actionsEl.innerHTML = actionBtnsHtml;

      const resBtn = document.getElementById("btnVirtualReserve");
      if (resBtn) resBtn.addEventListener("click", handleReserveClick);

      const pickupBtn = document.getElementById("btnVirtualPickup");
      if (pickupBtn) pickupBtn.addEventListener("click", () => showVirtualScannerModal(isConsumable ? "usage" : "pickup", userReservation));

      const returnBtn = document.getElementById("btnVirtualReturn");
      if (returnBtn) returnBtn.addEventListener("click", () => showVirtualScannerModal("return", userActiveLoan));

      const routeBtn = document.getElementById("btnGuideRoute");
      if (routeBtn) routeBtn.addEventListener("click", toggleRouteGuide);
    }
  }

  // 6. 예약 처리 핸들러
  async function handleReserveClick() {
    if (!window.LabBotAuth) return;
    const session = await LabBotAuth.currentSession();
    if (!session) {
      // "warning" 타입은 toast.js에 대응하는 CSS가 없어서(성공/실패/안내 3종류뿐)
      // 아무 색도 안 입혀진 채로 뜬다 — 이 앱에서 안내성 경고는 "info"(앰버색)로 처리한다.
      if (window.LabBotToast) LabBotToast.show("로그인이 필요한 기능입니다.", "info");
      setTimeout(() => (window.location.href = "login.html"), 1000);
      return;
    }

    if (!_matchedItem) return;

    try {
      if (window.LabBotRentals) {
        await LabBotRentals.reserveItem(_matchedItem, session, "manual");
      }
      if (window.LabBotToast) {
        LabBotToast.show(`[${_matchedItem.name}] 예약이 완료되었습니다. 가상 픽업 스캔을 진행하세요!`, "success");
      }
      await loadDbItems();
      await loadUserLoans();
      updateInspectorPanel();
      renderLabCanvas();
    } catch (err) {
      console.error("[VirtualLab] Reservation error:", err);
      if (window.LabBotToast) LabBotToast.show(err.message || "예약에 실패했습니다.", "error");
    }
  }

  // 7. 가상 스캐너 모달 & 픽업/반납 확인
  function showVirtualScannerModal(mode, loan) {
    const modalContainer = document.getElementById("scannerModalContainer");
    if (!modalContainer || !loan) return;

    modalContainer.innerHTML = `
      <div class="virtual-scanner-overlay" id="scannerOverlay">
        <div class="virtual-scanner-modal">
          <h3>${mode === "pickup" ? "가상 QR 수령 스캔" : mode === "usage" ? "가상 QR 사용 스캔" : "가상 QR 반납 스캔"}</h3>
          <p style="color:var(--text-muted); font-size:0.85rem; margin-top:4px;">
            디지털 트윈 로봇이 대상 물품의 QR 라벨을 확인 중입니다.
          </p>
          <div class="scanner-viewfinder">
            <div class="scanner-laser-line"></div>
            <div style="font-family:var(--font-mono); color:var(--accent-text); font-size:0.8rem; z-index:5;">
              [SCANNING ITEM]
            </div>
          </div>
          ${mode === "usage" ? `
            <label for="virtualUsageQty" style="display:block; margin:0.75rem 0; color:var(--text);">
              사용 수량
              <input id="virtualUsageQty" type="number" min="1" max="${Math.max(1, (loan.items?.available_qty || 0) + 1)}" value="1"
                style="width:100%; margin-top:0.35rem; padding:0.55rem; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:var(--radius-sm);" />
            </label>` : ""}
          <button class="btn-virtual-action btn-virtual-scan" id="btnConfirmScanAction">
            스캔 인식 완료 (서버 검증 실행)
          </button>
          <button class="btn-virtual-action btn-virtual-route" style="margin-top:0.5rem;" id="btnCloseScanner">
            닫기
          </button>
        </div>
      </div>
    `;

    document.getElementById("btnCloseScanner").addEventListener("click", () => {
      modalContainer.innerHTML = "";
    });

    document.getElementById("btnConfirmScanAction").addEventListener("click", async () => {
      try {
        const rpcName = mode === "pickup"
          ? "confirm_virtual_loan_pickup"
          : mode === "usage"
            ? "confirm_virtual_item_usage"
            : "confirm_virtual_loan_return";
        const rpcParams = {
          p_loan_id: loan.id,
          p_scene_object_id: _selectedVirtualObj.sceneObjectId,
        };
        if (mode === "usage") {
          rpcParams.p_qty = Number(document.getElementById("virtualUsageQty")?.value || 1);
        }
        const { error } = await supabaseClient.rpc(rpcName, rpcParams);
        if (error) throw error;

        if (mode === "pickup") {
          if (window.LabBotToast) LabBotToast.show("수령이 성공적으로 확정되었습니다! (대여중 전이)", "success");
        } else if (mode === "usage") {
          if (window.LabBotToast) LabBotToast.show("소모품 사용과 재고 차감이 확정되었습니다!", "success");
        } else {
          if (window.LabBotToast) LabBotToast.show("반납이 완료되었습니다!", "success");
        }

        modalContainer.innerHTML = "";
        await loadDbItems();
        await loadUserLoans();
        updateInspectorPanel();
        renderLabCanvas();
      } catch (err) {
        console.error("[VirtualLab] Scan verify error:", err);
        if (window.LabBotToast) LabBotToast.show(err.message || "스캔 검증에 실패했습니다.", "error");
      }
    });
  }

  // 8. 로봇 이동 경로 가이드 토글
  function toggleRouteGuide() {
    _routeActive = !_routeActive;
    renderLabCanvas();
    if (window.LabBotToast) {
      LabBotToast.show(_routeActive ? "로봇 순찰 및 안내 경로가 표시되었습니다." : "경로 표시를 해제했습니다.", "info");
    }
  }

  // 구역 필터링
  function filterByRoom(roomId) {
    _currentFilterRoom = roomId;
    renderRoomTabs();
    renderLabCanvas();
  }

  // 물품 ID로 포커싱
  function focusItemById(itemId) {
    const item = _itemsMap.get(itemId);
    if (!item) return;

    const vObj = VIRTUAL_LAB_OBJECTS.find(
      (o) => o.itemId === itemId || (o.itemQuery && item.name.toLowerCase().includes(o.itemQuery.toLowerCase()))
    );

    if (vObj) {
      _currentFilterRoom = "all";
      renderRoomTabs();
      selectObjectById(vObj.sceneObjectId);
      if (window.LabBotToast) {
        LabBotToast.show(`가상 실험실에서 [${item.name}] 위치를 찾았습니다!`, "info");
      }
    }
  }

  function setupEventListeners() {
    const searchInput = document.getElementById("labSearchInput");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        const query = e.target.value.trim().toLowerCase();
        if (!query) {
          renderLabCanvas();
          return;
        }

        const found = VIRTUAL_LAB_OBJECTS.find((o) => {
          const item = findMatchingItem(o);
          const name = item ? item.name : o.displayNameFallback;
          return name.toLowerCase().includes(query) || o.label.toLowerCase().includes(query);
        });

        if (found) {
          selectObjectById(found.sceneObjectId);
        }
      });
    }
  }

  // 9. Supabase Realtime 구독
  function subscribeRealtime() {
    if (!window.supabaseClient) return;

    supabaseClient
      .channel("virtual-lab-changes")
      .on("postgres_changes", { event: "*", schema: "public", table: "items" }, () => {
        loadDbItems().then(() => {
          renderLabCanvas();
          if (_selectedVirtualObj) updateInspectorPanel();
        });
      })
      .on("postgres_changes", { event: "*", schema: "public", table: "loans" }, () => {
        loadUserLoans().then(() => {
          if (_selectedVirtualObj) updateInspectorPanel();
        });
      })
      .subscribe();
  }

  window.addEventListener("DOMContentLoaded", initVirtualLab);
})();
