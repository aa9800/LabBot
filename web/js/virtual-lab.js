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
  let _isaacMap = null;
  let _isaacObjectMap = new Map();
  let _storageLocationMap = new Map();
  let _selectedStorageLocation = null;

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
    await loadIsaacMap();
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
    // auth.js가 내보내는 이름은 getSession이다(currentSession은 존재하지 않는다).
    // 게다가 이 호출이 try 밖에 있어서, TypeError가 initVirtualLab()까지 그대로 올라가
    // renderLabCanvas() 이후가 통째로 실행되지 않았다 — 캔버스가 빈 화면이던 원인.
    // 세션 조회 실패가 캔버스 렌더까지 막지 않도록 try 안으로 넣는다.
    try {
      const session = await LabBotAuth.getSession();
      if (!session) return;

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

  function getItemVisualState(vObj) {
    const matched = findMatchingItem(vObj);
    const status = matched ? computeStockStatus(matched) : "AVAILABLE";
    let color = "#4f7942";
    if (status === "OUT_OF_STOCK" || status === "EXPIRED") color = "#dc2626";
    if (status === "LOW_STOCK" || status === "EXPIRING_SOON") color = "#d97706";
    if (status === "MAINTENANCE") color = "#7c8280";
    return { matched, status, color, name: matched ? matched.name : vObj.displayNameFallback };
  }

  async function loadIsaacMap() {
    const response = await fetch("data/isaac_lab_map.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Isaac 웹 맵을 불러오지 못했습니다. (${response.status})`);
    const payload = await response.json();
    if (!payload.world || !Array.isArray(payload.fixtures) || !Array.isArray(payload.mapped_objects) || !Array.isArray(payload.storage_locations)) {
      throw new Error("Isaac 웹 맵 스키마가 올바르지 않습니다.");
    }
    _isaacMap = payload;
    _isaacObjectMap = new Map(payload.mapped_objects.map((row) => [row.scene_object_id, row]));
    _storageLocationMap = new Map(payload.storage_locations.map((row) => [row.location, row]));
  }

  function getAllDbItems() {
    return Array.from(_itemsMap.entries())
      .filter(([key]) => typeof key === "number")
      .map(([, item]) => item);
  }

  function getStorageItems(location) {
    return getAllDbItems().filter((item) => resolveStorageLocation(item) === location);
  }

  function resolveStorageLocation(item) {
    if (_storageLocationMap.has(item.location)) return item.location;
    if (item.item_type === "CONSUMABLE") return "소모품보관실";
    if (item.item_type === "PPE" || item.item_type === "SAFETY") return "안전장비함";
    if (item.item_type === "REAGENT") return "시약보관실";
    return "일반실험실";
  }

  function worldToPercent(point) {
    const bounds = {
      minX: _isaacMap.world.min_x,
      maxX: _isaacMap.world.max_x,
      minY: _isaacMap.world.min_y,
      maxY: _isaacMap.world.max_y
    };
    return [
      ((point[0] - bounds.minX) / (bounds.maxX - bounds.minX)) * 100,
      ((bounds.maxY - point[1]) / (bounds.maxY - bounds.minY)) * 100
    ];
  }

  function worldRectStyle(bbox) {
    const bounds = _isaacMap.world;
    const left = ((bbox.min[0] - bounds.min_x) / (bounds.max_x - bounds.min_x)) * 100;
    const top = ((bounds.max_y - bbox.max[1]) / (bounds.max_y - bounds.min_y)) * 100;
    const width = ((bbox.max[0] - bbox.min[0]) / (bounds.max_x - bounds.min_x)) * 100;
    const height = ((bbox.max[1] - bbox.min[1]) / (bounds.max_y - bounds.min_y)) * 100;
    return `left:${left}%;top:${top}%;width:${width}%;height:${height}%`;
  }

  function buildRouteSvg() {
    if (!_routeActive || !_selectedVirtualObj) return "";
    const mapObject = _selectedStorageLocation
      ? _storageLocationMap.get(_selectedStorageLocation)
      : _isaacObjectMap.get(_selectedVirtualObj.sceneObjectId);
    const configuredRoute = mapObject ? mapObject.route || [] : [];
    const points = configuredRoute.length && (configuredRoute[0][0] !== 0 || configuredRoute[0][1] !== 0)
      ? [[0, 0], ...configuredRoute]
      : configuredRoute;
    if (points.length < 2) return "";
    const projected = points.map(worldToPercent);
    const pointString = projected.map(([x, y]) => `${x},${y}`).join(" ");
    const checkpoints = projected.slice(1).map(([x, y], index) => `
      <g class="overview-checkpoint" transform="translate(${x} ${y})">
        <circle r="1.7"></circle><circle r="0.55"></circle>
        <text x="2.8" y="-2">CP-${index + 1}</text>
      </g>`).join("");
    return `<svg class="overview-route" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="로봇 안내 경로">
      <polyline points="${pointString}"></polyline>${checkpoints}
    </svg>`;
  }

  function renderOverview() {
    const fixtures = _isaacMap.fixtures.map((fixture) => `
      <div class="sim-fixture sim-fixture-${fixture.type}" style="${worldRectStyle(fixture.bbox)}">
        <span>${fixture.label}</span>
      </div>`).join("");
    const partitions = _isaacMap.architecture.map((wall) => `
      <div class="sim-partition" style="${worldRectStyle(wall.bbox)}"></div>`).join("");

    const storageNodes = _isaacMap.storage_locations.map((storage) => {
      if (_currentFilterRoom !== "all" && storage.location !== _currentFilterRoom) return "";
      const items = getStorageItems(storage.location);
      const [x, y] = worldToPercent(storage.bbox.center);
      const selected = _selectedStorageLocation === storage.location;
      const alertCount = items.filter((item) => computeStockStatus(item) !== "AVAILABLE").length;
      return `<button type="button" class="overview-storage ${selected ? "is-selected" : ""}"
        style="left:${x}%;top:${y}%" data-storage-location="${escapeHtml(storage.location)}"
        aria-label="${escapeHtml(storage.location)} 보관 물품 ${items.length}종">
        <b>${escapeHtml(storage.shelf_code || storage.location)}</b><span>${items.length}종</span>${alertCount ? `<em>${alertCount} 경고</em>` : ""}
      </button>`;
    }).join("");

    const nodes = _isaacMap.mapped_objects.map((mapObject) => {
      const vObj = VIRTUAL_LAB_OBJECTS.find((entry) => entry.sceneObjectId === mapObject.scene_object_id);
      if (!vObj) return "";
      if (_currentFilterRoom !== "all" && mapObject.room !== _currentFilterRoom) return "";
      const [x, y] = worldToPercent(mapObject.bbox.center);
      const state = getItemVisualState(vObj);
      const selected = _selectedVirtualObj && _selectedVirtualObj.sceneObjectId === vObj.sceneObjectId;
      return `<button type="button" class="overview-item ${selected ? "is-selected" : ""}"
        style="left:${x}%;top:${y}%;--item-color:${state.color}" data-obj-id="${vObj.sceneObjectId}"
        aria-label="${state.name}"><span></span><em>${vObj.label}</em></button>`;
    }).join("");

    const [robotX, robotY] = worldToPercent([0, 0]);
    return `<div class="overview-map physical-map"><div class="overview-grid"></div>
      <div class="sim-floor-outline"></div>${fixtures}${partitions}${buildRouteSvg()}${storageNodes}${nodes}
      <div class="overview-robot" style="left:${robotX}%;top:${robotY}%"><span>RZ</span><small>WORLD 0,0</small></div>
      <div class="sim-axis sim-axis-x">X −7m ↔ +7m</div><div class="sim-axis sim-axis-y">Y −2m ↔ +16m</div>
      <div class="overview-map-title"><b>ISAAC LAB · TOP VIEW 1:1</b><span>USD ${_isaacMap.source.asset_sha256.slice(0, 10)} · DB ${getAllDbItems().length}종 · 9 storage nodes</span></div>
    </div>`;
  }

  function renderRoomDetail(roomId) {
    const room = VIRTUAL_LAB_ROOM_LAYOUTS.find((entry) => entry.id === roomId);
    const roomObjects = VIRTUAL_LAB_OBJECTS.filter((obj) => obj.room === roomId);
    const stations = Array.from({ length: 6 }, (_, index) => {
      const vObj = roomObjects[index];
      const stationType = index < 3 ? "SHELF" : "BENCH";
      let content = `<span class="station-empty">EMPTY · AVAILABLE FOR MAPPING</span>`;
      if (vObj) {
        const state = getItemVisualState(vObj);
        const selected = _selectedVirtualObj && _selectedVirtualObj.sceneObjectId === vObj.sceneObjectId;
        content = `<button type="button" class="station-item ${selected ? "is-selected" : ""}"
          data-obj-id="${vObj.sceneObjectId}" style="--item-color:${state.color}">
          <span class="station-status"></span><span><b>${vObj.label}</b><small>${state.name}</small></span>
        </button>`;
      }
      return `<section class="room-station"><header>${stationType} ${String(index % 3 + 1).padStart(2, "0")}</header><div>${content}</div></section>`;
    }).join("");
    return `<div class="room-detail-map"><div class="overview-grid"></div>
      <button type="button" class="room-back-btn" data-room-id="all">← 전체 조감도</button>
      <div class="room-detail-heading"><span>${room ? room.code : "ZONE"}</span><strong>${roomId}</strong><small>${room ? room.label : ""}</small></div>
      <div class="room-stations">${stations}</div>
      <div class="overview-robot room-robot"><span>RZ</span><small>ENTRY</small></div>
    </div>`;
  }

  // 4. 시뮬레이터 좌표 기반 운영 조감도 렌더링
  function renderLabCanvas() {
    const canvas = document.getElementById("labCanvas");
    if (!canvas) return;
    canvas.innerHTML = renderOverview();

    canvas.querySelectorAll("[data-obj-id]").forEach((el) => {
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        selectObjectById(el.getAttribute("data-obj-id"));
      });
    });
    canvas.querySelectorAll("[data-storage-location]").forEach((el) => {
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        selectStorageLocation(el.getAttribute("data-storage-location"));
      });
    });
    canvas.querySelectorAll("[data-room-id]").forEach((el) => {
      el.addEventListener("click", () => filterByRoom(el.getAttribute("data-room-id")));
    });
  }

  // 5. 물체 선택 및 사이드 인스펙터 패널 갱신
  function selectObjectById(sceneObjectId) {
    const vObj = VIRTUAL_LAB_OBJECTS.find((o) => o.sceneObjectId === sceneObjectId);
    if (!vObj) return;

    _selectedVirtualObj = vObj;
    _selectedStorageLocation = null;
    _matchedItem = findMatchingItem(vObj);

    renderLabCanvas();
    updateInspectorPanel();
  }

  function selectStorageLocation(location, preferredItemId = null) {
    const storage = _storageLocationMap.get(location);
    if (!storage) return;
    const items = getStorageItems(location);
    const matched = items.find((item) => item.id === preferredItemId) || items[0] || null;
    const dbBinding = matched
      ? Array.from(_sceneBindings.entries()).find(([, binding]) => binding.item_id === matched.id)
      : null;
    _selectedStorageLocation = location;
    _matchedItem = matched;
    _selectedVirtualObj = {
      sceneObjectId: dbBinding ? dbBinding[0] : `storage:${location}`,
      label: storage.shelf_code || "STORAGE",
      displayNameFallback: `${location} 보관 물품`,
      category: matched ? matched.category : "INVENTORY",
      room: location,
      zoneTag: `${storage.shelf_code || location} · ${items.length}종`,
      description: `${location}의 Isaac 보관 설비에 연결된 DB 물품입니다.`
    };
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
    const shelfCodeEl = document.getElementById("inspectShelfCode");
    const isaacPositionEl = document.getElementById("inspectIsaacPosition");
    const robotTargetEl = document.getElementById("inspectRobotTarget");
    const primPathEl = document.getElementById("inspectPrimPath");
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
    const locationMap = _selectedStorageLocation
      ? _storageLocationMap.get(_selectedStorageLocation)
      : _isaacObjectMap.get(_selectedVirtualObj.sceneObjectId);
    const isaacPosition = locationMap && locationMap.bbox ? locationMap.bbox.center : null;
    const robotTarget = locationMap ? locationMap.robot_target : null;

    if (titleEl) titleEl.innerText = `${_selectedVirtualObj.label}: ${itemName}`;
    if (roomEl) roomEl.innerText = `${room} (${_selectedVirtualObj.zoneTag})`;
    if (categoryEl) categoryEl.innerText = category;
    if (stockEl) stockEl.innerText = stockStr;
    if (statusEl) statusEl.innerText = statusLabel;
    if (storageEl) storageEl.innerText = storage;
    if (expiresEl) expiresEl.innerText = expires;
    if (shelfCodeEl) shelfCodeEl.innerText = locationMap?.shelf_code || "미지정";
    if (isaacPositionEl) isaacPositionEl.innerText = isaacPosition
      ? `X ${isaacPosition[0].toFixed(2)}m · Y ${isaacPosition[1].toFixed(2)}m`
      : "좌표 없음";
    if (robotTargetEl) robotTargetEl.innerText = robotTarget
      ? `X ${Number(robotTarget[0]).toFixed(2)}m · Y ${Number(robotTarget[1]).toFixed(2)}m`
      : "정차점 없음";
    if (primPathEl) {
      primPathEl.innerText = locationMap?.prim_path || locationMap?.fixture_prim_path || "미지정";
      primPathEl.title = primPathEl.innerText;
    }
    if (descEl) descEl.innerText = _selectedVirtualObj.description;

    // 해당 물품에 대한 사용자 예약 건이 있는지 확인
    const userReservation = matched ? _activeUserLoans.find((l) => l.item_id === matched.id && l.status === "예약중") : null;
    const userActiveLoan = matched ? _activeUserLoans.find((l) => l.item_id === matched.id && l.status === "대여중") : null;
    const isConsumable = matched && window.LabBotRentals && window.LabBotRentals.isConsumable(matched);

    let actionBtnsHtml = "";
    if (_selectedStorageLocation) {
      const storageItems = getStorageItems(_selectedStorageLocation);
      actionBtnsHtml += `<div class="storage-inventory-list"><strong>${escapeHtml(_selectedStorageLocation)} 물품 ${storageItems.length}종</strong><div>`;
      actionBtnsHtml += storageItems.map((item) => {
        const status = computeStockStatus(item);
        return `<button type="button" class="storage-inventory-item ${_matchedItem && _matchedItem.id === item.id ? "is-selected" : ""}" data-storage-item-id="${item.id}">
          <span>${escapeHtml(item.name)}</span><small>${escapeHtml(STOCK_STATUS_LABEL[status] || status)} · ${item.available_qty}/${item.total_qty} ${escapeHtml(item.unit || "개")}</small>
        </button>`;
      }).join("");
      actionBtnsHtml += `</div></div>`;
    }

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

      actionsEl.querySelectorAll("[data-storage-item-id]").forEach((button) => {
        button.addEventListener("click", () => selectStorageLocation(_selectedStorageLocation, Number(button.getAttribute("data-storage-item-id"))));
      });
    }
  }

  // 6. 예약 처리 핸들러
  async function handleReserveClick() {
    if (!window.LabBotAuth) return;
    const session = await LabBotAuth.getSession();
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
    if (_routeActive) {
      _currentFilterRoom = "all";
      renderRoomTabs();
    }
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

    const directBinding = Array.from(_sceneBindings.entries()).find(([, binding]) => binding.item_id === itemId);
    const vObj = VIRTUAL_LAB_OBJECTS.find((o) => o.itemId === itemId || (directBinding && o.sceneObjectId === directBinding[0]));

    if (vObj) {
      _currentFilterRoom = "all";
      renderRoomTabs();
      selectObjectById(vObj.sceneObjectId);
      if (window.LabBotToast) {
        LabBotToast.show(`가상 실험실에서 [${item.name}] 위치를 찾았습니다!`, "info");
      }
    } else {
      _currentFilterRoom = "all";
      renderRoomTabs();
      selectStorageLocation(resolveStorageLocation(item), item.id);
      if (window.LabBotToast) LabBotToast.show(`가상 실험실에서 [${item.name}] 보관 위치를 찾았습니다!`, "info");
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

        const foundItem = getAllDbItems().find((item) => item.name.toLowerCase().includes(query));
        if (foundItem) {
          focusItemById(foundItem.id);
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
