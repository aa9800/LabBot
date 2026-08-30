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
  let _routeItemId = null;
  let _isaacMap = null;
  let _isaacObjectMap = new Map();
  let _storageLocationMap = new Map();
  let _selectedStorageLocation = null;
  let _catalogLoadState = "loading";
  let _robotTelemetryTimer = null;
  let _robotTelemetryBusy = false;
  let _guideStatus = { status: "idle" };
  let _robotPose = {
    x: 0,
    y: 0,
    headingDeg: 90,
    connected: false,
    hasWorldPose: false,
    source: "isaac",
    updatedAt: 0
  };

  const ROBOT_TELEMETRY_INTERVAL_MS = 250;
  const ROBOT_TELEMETRY_STALE_MS = 1800;
  const SIM_ROOM_AREAS = [
    { location: "입구 공용비품 보관구역", code: "ENT-COM", kind: "entry", min: [-6.85, -9.85], max: [6.85, -2.05], anchor: [0, -6] },
    { location: "일반실험실", code: "GEN", kind: "general", min: [-6.85, -1.85], max: [6.85, 9.35], anchor: [-5.0, 8.55] },
    { location: "안전장비함", code: "SAF", kind: "safety", min: [-6.8, -1.72], max: [-4.85, -0.12], anchor: [-5.82, -0.92] },
    { location: "기기실-1", code: "EQ-1", kind: "equipment", min: [-6.85, 9.4], max: [-2.55, 11.45], anchor: [-4.72, 9.82] },
    { location: "기기실-2", code: "EQ-2", kind: "equipment", min: [-6.85, 11.55], max: [-2.55, 13.85], anchor: [-4.72, 12.0] },
    { location: "세포배양실", code: "CELL", kind: "cell", min: [-6.85, 13.95], max: [-2.55, 15.85], anchor: [-4.72, 14.35] },
    { location: "소모품보관실", code: "CON", kind: "storage", min: [2.55, 9.4], max: [6.85, 11.45], anchor: [4.72, 9.82] },
    { location: "냉장보관실", code: "4C", kind: "cold", min: [2.55, 11.55], max: [4.35, 13.85], anchor: [3.42, 12.0] },
    { location: "냉동보관실", code: "-80C", kind: "frozen", min: [4.35, 11.55], max: [6.85, 13.85], anchor: [5.62, 12.0] },
    { location: "시약보관실", code: "REAG", kind: "reagent", min: [-2.4, 13.95], max: [6.85, 15.85], anchor: [0.2, 14.35] }
  ];
  const LOCATION_META = {
    "입구 공용비품 보관구역": { name: "입구 공용비품", icon: "tips" },
    "일반실험실": { name: "중앙 실험실", icon: "microscope" },
    "안전장비함": { name: "안전장비 보관소", icon: "safety" },
    "기기실-1": { name: "기기 분석실 1", icon: "pcr" },
    "기기실-2": { name: "기기 분석실 2", icon: "centrifuge" },
    "세포배양실": { name: "세포배양실", icon: "microscope" },
    "소모품보관실": { name: "소모품 보관소", icon: "tips" },
    "냉장보관실": { name: "냉장보관소", icon: "freezer" },
    "냉동보관실": { name: "냉동보관소", icon: "freezer" },
    "시약보관실": { name: "시약 보관소", icon: "reagent" }
  };
  const FIXTURE_TYPE_LABELS = {
    aisle: "AMR NAVIGATION AISLE",
    bench: "MODULAR LAB BENCH",
    equipment: "INSTRUMENT STATION",
    storage: "BIN STORAGE RACK",
    cold: "COLD STORAGE",
    reagent: "REAGENT PREP",
    safety: "SAFETY FIXTURE",
    dock: "ROBOT DOCK"
  };

  const ITEM_CATALOG_COLUMNS = [
    "id", "name", "category", "location", "item_type", "available_qty", "total_qty",
    "minimum_qty", "unit", "status", "manual_status", "storage_condition", "expires_at", "notes",
    "is_rentable", "storage_parent_item_id", "storage_position"
  ].join(",");

  const BINDING_COLUMNS = [
    "scene_object_id", "item_id", "room", "display_mode", "zone_type", "access_level",
    "shelf_code", "shelf_row", "shelf_slot", "location_detail", "nav_x", "nav_y", "nav_heading"
  ].join(",");

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
    startRobotTelemetrySync();

    // URL 파라미터 확인 (?findItem=12 or ?room=기기실-1)
    const urlParams = new URLSearchParams(window.location.search);
    const targetItemId = urlParams.get("findItem");
    const targetRoom = urlParams.get("room");
    const startGuide = urlParams.get("guide") === "1";
    const targetLoanId = urlParams.get("loanId");

    if (targetRoom) {
      filterByRoom(targetRoom);
    }
    if (targetItemId) {
      const parsedItemId = parseInt(targetItemId, 10);
      focusItemById(parsedItemId);
      if (startGuide) {
        const reservation = _activeUserLoans.find((loan) => (
          loan.status === "예약중"
          && Number(loan.item_id) === parsedItemId
          && (!targetLoanId || String(loan.id) === targetLoanId)
        ));
        if (reservation) {
          await beginRobotGuide(reservation, { notify: true });
        } else {
          _routeActive = true;
          _routeItemId = parsedItemId;
          _guideStatus = { status: "preview" };
          renderLabCanvas();
          updateInspectorPanel();
        }
      }
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
    _catalogLoadState = "loading";
    updateInventorySyncBadge();
    try {
      const { data, error } = await supabaseClient
        .from("items")
        .select(ITEM_CATALOG_COLUMNS)
        .order("name", { ascending: true });

      if (error) throw error;

      _itemsMap.clear();
      (data || []).forEach((item) => {
        _itemsMap.set(item.id, item);
        _itemsMap.set(item.name, item);
      });

      // RLS가 조회를 막으면 Supabase는 오류 대신 200 + 빈 배열을 반환할 수 있다.
      // 실제 동기화처럼 보이는 "DB 0종"을 표시하지 않고 권한 상태를 명확히 구분한다.
      _catalogLoadState = data && data.length > 0 ? "ready" : "restricted";

      let { data: bindings, error: bindingError } = await supabaseClient
        .from("virtual_lab_objects")
        .select(BINDING_COLUMNS)
        .eq("enabled", true);

      // 상세 위치 마이그레이션 전 운영 DB도 화면 전체가 깨지지 않도록 구형 컬럼으로 재시도한다.
      if (bindingError && bindingError.code === "42703") {
        const legacyResult = await supabaseClient
          .from("virtual_lab_objects")
          .select("scene_object_id, item_id, room, display_mode")
          .eq("enabled", true);
        bindings = legacyResult.data;
        bindingError = legacyResult.error;
      }

      if (bindingError) {
        console.warn("[VirtualLab] virtual_lab_objects migration is not applied yet:", bindingError);
        _sceneBindings.clear();
      } else {
        _sceneBindings = new Map((bindings || []).map((row) => [row.scene_object_id, row]));
      }

      console.log(`[VirtualLab] Supabase items loaded: ${data ? data.length : 0} items`);
    } catch (err) {
      _catalogLoadState = "error";
      _itemsMap.clear();
      _sceneBindings.clear();
      console.error("[VirtualLab] Failed to load DB items:", err);
      if (window.LabBotToast) {
        LabBotToast.show("물품 데이터를 불러오는 중 오류가 발생했습니다.", "error");
      }
    } finally {
      updateInventorySyncBadge();
    }
  }

  function updateInventorySyncBadge() {
    const badge = document.getElementById("inventorySyncBadge");
    if (!badge) return;
    if (_catalogLoadState === "ready") {
      badge.innerText = "INVENTORY: SUPABASE LIVE";
      badge.dataset.state = "ready";
      return;
    }
    if (_catalogLoadState === "restricted") {
      badge.innerText = "INVENTORY: DB 조회 권한 확인 필요";
      badge.dataset.state = "restricted";
      return;
    }
    if (_catalogLoadState === "error") {
      badge.innerText = "INVENTORY: DB 연결 오류";
      badge.dataset.state = "error";
      return;
    }
    badge.innerText = "INVENTORY: 동기화 중";
    badge.dataset.state = "loading";
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

  function getContainedItems(parentItemId) {
    return getAllDbItems().filter((item) => item.storage_parent_item_id === parentItemId);
  }

  function findBindingEntryForItem(itemId) {
    if (!itemId) return null;
    return Array.from(_sceneBindings.entries()).find(([, binding]) => binding.item_id === itemId) || null;
  }

  function formatShelfPosition(binding, fallbackShelfCode = "미지정") {
    const parts = [binding?.shelf_code || fallbackShelfCode];
    if (binding?.shelf_row) parts.push(`${binding.shelf_row}단`);
    if (binding?.shelf_slot) parts.push(`${binding.shelf_slot}칸`);
    return parts.join(" · ");
  }

  function getCatalogSummary() {
    if (_catalogLoadState === "ready") return "SUPABASE LIVE";
    if (_catalogLoadState === "restricted") return "DB 조회 권한 확인 필요";
    if (_catalogLoadState === "error") return "DB 연결 오류";
    return "DB 동기화 중";
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

  function worldAreaStyle(area) {
    return worldRectStyle({ min: [area.min[0], area.min[1]], max: [area.max[0], area.max[1]] });
  }

  function sameWorldPoint(a, b, tolerance = 0.04) {
    return Boolean(a && b && Math.hypot(Number(a[0]) - Number(b[0]), Number(a[1]) - Number(b[1])) <= tolerance);
  }

  function dedupeWorldPoints(points) {
    return points.reduce((result, point) => {
      if (!Array.isArray(point) || !Number.isFinite(Number(point[0])) || !Number.isFinite(Number(point[1]))) return result;
      const normalized = [Number(point[0]), Number(point[1])];
      if (!result.length || !sameWorldPoint(result[result.length - 1], normalized)) result.push(normalized);
      return result;
    }, []);
  }

  function getSelectedMapObject() {
    if (!_selectedVirtualObj) return null;
    return _selectedStorageLocation
      ? _storageLocationMap.get(_selectedStorageLocation)
      : _isaacObjectMap.get(_selectedVirtualObj.sceneObjectId);
  }

  function guideMatchesSelectedItem() {
    if (!_matchedItem) return false;
    if (_guideStatus?.item_id !== undefined && _guideStatus?.item_id !== null) {
      return Number(_guideStatus.item_id) === Number(_matchedItem.id);
    }
    if (_guideStatus?.item_name) {
      return String(_guideStatus.item_name).trim() === String(_matchedItem.name).trim();
    }
    return Number(_routeItemId) === Number(_matchedItem.id);
  }

  function getActiveRoutePoints() {
    const mapObject = getSelectedMapObject();
    if (!mapObject) return [];

    let route = Array.isArray(mapObject.route) ? mapObject.route.map((point) => [...point]) : [];
    const bindingEntry = _matchedItem ? findBindingEntryForItem(_matchedItem.id) : null;
    const binding = bindingEntry ? bindingEntry[1] : null;
    const bindingTarget = Number.isFinite(binding?.nav_x) && Number.isFinite(binding?.nav_y)
      ? [Number(binding.nav_x), Number(binding.nav_y)]
      : null;
    const target = bindingTarget || mapObject.robot_target;
    if (target && (!route.length || !sameWorldPoint(route[route.length - 1], target))) route.push([...target]);

    const start = _robotPose.hasWorldPose ? [_robotPose.x, _robotPose.y] : [0, 0];
    if (_robotPose.hasWorldPose && route.length) {
      const nearestIndex = route.reduce((bestIndex, point, index) => (
        Math.hypot(point[0] - start[0], point[1] - start[1])
          < Math.hypot(route[bestIndex][0] - start[0], route[bestIndex][1] - start[1])
          ? index
          : bestIndex
      ), 0);
      let routeStartIndex = nearestIndex;
      const guideIndex = Number(_guideStatus?.waypoint_index);
      const waypointCount = Number(_guideStatus?.waypoint_count);
      if (guideMatchesSelectedItem() && ["navigating", "arrived"].includes(_guideStatus?.status) && Number.isFinite(guideIndex)) {
        const guideRouteStart = Number.isFinite(waypointCount)
          ? Math.max(0, route.length - waypointCount)
          : 0;
        routeStartIndex = Math.max(routeStartIndex, guideRouteStart + guideIndex);
      }
      route = route.slice(Math.min(routeStartIndex, route.length - 1));
    }

    if (!route.length) route = [start, target].filter(Boolean);
    else if (sameWorldPoint(start, route[0])) route[0] = start;
    else route.unshift(start);
    return dedupeWorldPoints(route);
  }

  function buildRoundedPath(points, radius = 1.25) {
    if (points.length < 2) return "";
    const fmt = (value) => Number(value).toFixed(3);
    let path = `M ${fmt(points[0][0])} ${fmt(points[0][1])}`;
    for (let index = 1; index < points.length - 1; index += 1) {
      const previous = points[index - 1];
      const current = points[index];
      const next = points[index + 1];
      const incomingLength = Math.hypot(current[0] - previous[0], current[1] - previous[1]);
      const outgoingLength = Math.hypot(next[0] - current[0], next[1] - current[1]);
      const cornerRadius = Math.min(radius, incomingLength / 2, outgoingLength / 2);
      const incoming = [
        current[0] - ((current[0] - previous[0]) / Math.max(incomingLength, 0.0001)) * cornerRadius,
        current[1] - ((current[1] - previous[1]) / Math.max(incomingLength, 0.0001)) * cornerRadius
      ];
      const outgoing = [
        current[0] + ((next[0] - current[0]) / Math.max(outgoingLength, 0.0001)) * cornerRadius,
        current[1] + ((next[1] - current[1]) / Math.max(outgoingLength, 0.0001)) * cornerRadius
      ];
      path += ` L ${fmt(incoming[0])} ${fmt(incoming[1])} Q ${fmt(current[0])} ${fmt(current[1])} ${fmt(outgoing[0])} ${fmt(outgoing[1])}`;
    }
    const last = points[points.length - 1];
    return `${path} L ${fmt(last[0])} ${fmt(last[1])}`;
  }

  function routeDistanceMeters(points) {
    return points.slice(1).reduce((total, point, index) => total + Math.hypot(
      point[0] - points[index][0],
      point[1] - points[index][1]
    ), 0);
  }

  function buildRouteSvg() {
    if (!_routeActive || !_selectedVirtualObj) return "";
    const points = getActiveRoutePoints();
    if (points.length < 2) return "";
    const projected = points.map(worldToPercent);
    const pathData = buildRoundedPath(projected);
    const checkpoints = projected.slice(1).map(([x, y], index) => `
      <g class="overview-checkpoint" transform="translate(${x} ${y})">
        <circle r="1.45"></circle><circle r="0.48"></circle>
        <text x="2.3" y="-1.8">${index === projected.length - 2 ? "DEST" : `W${index + 1}`}</text>
      </g>`).join("");
    const distance = routeDistanceMeters(points);
    return `<svg class="overview-route" id="overviewRouteOverlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="로봇 안내 경로 ${distance.toFixed(1)}미터">
      <defs><marker id="routeArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>
      <path class="overview-route-halo" d="${pathData}"></path>
      <path class="overview-route-main" d="${pathData}" marker-end="url(#routeArrow)"></path>
      ${checkpoints}
      <g class="overview-route-label" transform="translate(${projected[0][0]} ${projected[0][1]})"><text x="2.3" y="3.4">앞으로 ${distance.toFixed(1)}m</text></g>
    </svg>`;
  }

  function buildRobotMarker() {
    const point = _robotPose.hasWorldPose ? [_robotPose.x, _robotPose.y] : [0, 0];
    const [robotX, robotY] = worldToPercent(point);
    const heading = Number.isFinite(_robotPose.headingDeg) ? _robotPose.headingDeg : 90;
    const stateClass = _robotPose.hasWorldPose ? "is-live" : _robotPose.connected ? "is-unlocalized" : "is-waiting";
    const label = _robotPose.hasWorldPose
      ? `X ${_robotPose.x.toFixed(2)} · Y ${_robotPose.y.toFixed(2)}`
      : _robotPose.connected ? "POSITION N/A" : "ISAAC WAIT";
    return `<div class="overview-robot ${stateClass}" id="overviewRobot" style="left:${robotX}%;top:${robotY}%">
      <div class="overview-robot-body" style="transform:rotate(${-heading}deg)">
        <svg class="overview-robot-icon" viewBox="0 0 44 44" aria-hidden="true">
          <rect class="robot-wheel" x="7" y="2" width="10" height="6" rx="2"></rect>
          <rect class="robot-wheel" x="27" y="2" width="10" height="6" rx="2"></rect>
          <rect class="robot-wheel" x="7" y="36" width="10" height="6" rx="2"></rect>
          <rect class="robot-wheel" x="27" y="36" width="10" height="6" rx="2"></rect>
          <rect class="robot-chassis" x="5" y="6" width="34" height="32" rx="10"></rect>
          <path class="robot-front" d="M31 10 L40 22 L31 34 Z"></path>
          <circle class="robot-camera-ring" cx="25" cy="22" r="7"></circle>
          <circle class="robot-camera" cx="25" cy="22" r="3.2"></circle>
          <path class="robot-sensor" d="M10 16h7M10 22h5M10 28h7"></path>
        </svg>
      </div>
      <small>${label}</small>
    </div>`;
  }

  function updateRobotSyncBadge() {
    const badge = document.getElementById("robotSyncBadge");
    if (!badge) return;

    if (_robotPose.hasWorldPose) {
      badge.textContent = `ROBOT: ISAAC LIVE · X ${_robotPose.x.toFixed(2)} · Y ${_robotPose.y.toFixed(2)}`;
      badge.dataset.state = "ready";
      return;
    }

    if (_robotPose.connected) {
      badge.textContent = "ROBOT: ISAAC LIVE · 위치 좌표 수신 대기";
      badge.dataset.state = "limited";
      return;
    }

    badge.textContent = "ROBOT: ISAAC 연결 대기";
    badge.dataset.state = "offline";
  }

  function updateRouteProgressBadge() {
    const badge = document.getElementById("routeProgressBadge");
    if (!badge) return;
    badge.hidden = !_routeActive;
    if (!_routeActive) return;

    const points = getActiveRoutePoints();
    const remaining = points.length > 1 ? routeDistanceMeters(points) : 0;
    const status = guideMatchesSelectedItem() ? (_guideStatus?.status || "preview") : "preview";
    if (status === "navigating") {
      const index = Number(_guideStatus.waypoint_index || 0) + 1;
      const count = Number(_guideStatus.waypoint_count || Math.max(1, points.length - 1));
      badge.textContent = `ROUTE: 이동 ${Math.min(index, count)}/${count} · ${remaining.toFixed(1)}m`;
      badge.dataset.state = "navigating";
    } else if (status === "arrived") {
      badge.textContent = `ROUTE: 목적지 도착 · ${_guideStatus.shelf_code || "선반 앞"}`;
      badge.dataset.state = "arrived";
    } else if (String(status).startsWith("awaiting_")) {
      badge.textContent = "ROUTE: 경로 미리보기 · 실물 주행 준비 필요";
      badge.dataset.state = "limited";
    } else {
      badge.textContent = `ROUTE: 경로 미리보기 · ${remaining.toFixed(1)}m`;
      badge.dataset.state = "preview";
    }
  }

  function refreshRouteOverlay() {
    if (!_routeActive) {
      updateRouteProgressBadge();
      return;
    }
    const map = document.querySelector(".physical-map");
    if (!map) return;
    const current = document.getElementById("overviewRouteOverlay");
    const markup = buildRouteSvg();
    if (current && markup) current.outerHTML = markup;
    else if (current) current.remove();
    else if (markup) map.insertAdjacentHTML("afterbegin", markup);
    updateRouteProgressBadge();
  }

  function applyRobotPoseToMap() {
    const marker = document.getElementById("overviewRobot");
    if (marker) {
      marker.classList.toggle("is-live", _robotPose.hasWorldPose);
      marker.classList.toggle("is-unlocalized", _robotPose.connected && !_robotPose.hasWorldPose);
      marker.classList.toggle("is-waiting", !_robotPose.connected);

      const label = marker.querySelector("small");
      if (_robotPose.hasWorldPose) {
        const [x, y] = worldToPercent([_robotPose.x, _robotPose.y]);
        marker.style.left = `${x}%`;
        marker.style.top = `${y}%`;
        const body = marker.querySelector(".overview-robot-body");
        if (body) body.style.transform = `rotate(${-_robotPose.headingDeg}deg)`;
        if (label) label.textContent = `X ${_robotPose.x.toFixed(2)} · Y ${_robotPose.y.toFixed(2)}`;
      } else if (label) {
        label.textContent = _robotPose.connected ? "POSITION N/A" : "ISAAC WAIT";
      }
    }
    updateRobotSyncBadge();
    refreshRouteOverlay();
  }

  async function pollRobotTelemetry() {
    if (_robotTelemetryBusy) return;
    _robotTelemetryBusy = true;
    try {
      const robotApi = window.LabBotRobotConsole;
      const telemetry = robotApi?.fetchTelemetry
        ? await robotApi.fetchTelemetry(800, "sim")
        : null;

      if (telemetry) {
        const x = Number(telemetry.x);
        const y = Number(telemetry.y);
        const heading = Number(telemetry.heading_deg);
        const hasWorldPose = telemetry.x !== null && telemetry.x !== undefined
          && telemetry.y !== null && telemetry.y !== undefined
          && Number.isFinite(x) && Number.isFinite(y);
        _robotPose = {
          ..._robotPose,
          x: hasWorldPose ? x : _robotPose.x,
          y: hasWorldPose ? y : _robotPose.y,
          headingDeg: Number.isFinite(heading) ? heading : _robotPose.headingDeg,
          connected: true,
          hasWorldPose,
          source: "isaac",
          updatedAt: Date.now()
        };
        _guideStatus = telemetry.guide || telemetry.mission || _guideStatus;
      } else if (Date.now() - _robotPose.updatedAt > ROBOT_TELEMETRY_STALE_MS) {
        _robotPose = {
          ..._robotPose,
          connected: false,
          hasWorldPose: false,
          source: "isaac"
        };
      }
      applyRobotPoseToMap();
    } finally {
      _robotTelemetryBusy = false;
      _robotTelemetryTimer = window.setTimeout(
        pollRobotTelemetry,
        document.hidden ? 1000 : ROBOT_TELEMETRY_INTERVAL_MS
      );
    }
  }

  function startRobotTelemetrySync() {
    if (_robotTelemetryTimer) window.clearTimeout(_robotTelemetryTimer);
    pollRobotTelemetry();
  }

  function buildRoomZones() {
    return SIM_ROOM_AREAS.map((area) => {
      if (_currentFilterRoom !== "all" && area.location !== _currentFilterRoom) return "";
      return `<div class="sim-room-zone sim-room-zone-${area.kind}" style="${worldAreaStyle(area)}" aria-hidden="true"></div>`;
    }).join("");
  }

  function buildGlassPartitions() {
    const partitions = window.VIRTUAL_LAB_SIM_GEOMETRY?.partitions || [];
    return partitions
      .filter((partition) => partition.h > partition.w * 4)
      .map((partition) => {
        const area = {
          min: [partition.x - partition.w / 2, partition.y - partition.h / 2],
          max: [partition.x + partition.w / 2, partition.y + partition.h / 2]
        };
        return `<div class="sim-glass-partition" style="${worldAreaStyle(area)}"></div>`;
      })
      .join("");
  }

  function renderOverview() {
    const fixtures = _isaacMap.fixtures.map((fixture) => `
      <div class="sim-fixture sim-fixture-${fixture.type}" style="${worldRectStyle(fixture.bbox)}"
        title="${escapeHtml(fixture.label)} · ${FIXTURE_TYPE_LABELS[fixture.type] || "LAB FIXTURE"}"></div>`).join("");
    const partitions = _isaacMap.architecture.map((wall) => `
      <div class="sim-partition" style="${worldRectStyle(wall.bbox)}"></div>`).join("");

    const storageNodes = _isaacMap.storage_locations.map((storage) => {
      if (_currentFilterRoom !== "all" && storage.location !== _currentFilterRoom) return "";
      const items = getStorageItems(storage.location);
      const area = SIM_ROOM_AREAS.find((entry) => entry.location === storage.location);
      const [x, y] = worldToPercent(area?.anchor || storage.bbox.center);
      const selected = _selectedStorageLocation === storage.location;
      const alertCount = items.filter((item) => computeStockStatus(item) !== "AVAILABLE").length;
      const meta = LOCATION_META[storage.location] || { name: storage.location, icon: "reagent" };
      return `<button type="button" class="overview-storage ${selected ? "is-selected" : ""}"
        style="left:${x}%;top:${y}%" data-storage-location="${escapeHtml(storage.location)}"
        aria-label="${escapeHtml(storage.location)} 보관 물품 ${items.length}종">
        <span class="overview-storage-icon">${SVG_ICONS[meta.icon] || SVG_ICONS.reagent}</span>
        <span class="overview-storage-copy"><strong>${escapeHtml(meta.name)}</strong><small>${escapeHtml(storage.shelf_code || area?.code || "STORAGE")}</small></span>
        ${alertCount ? `<i title="재고 확인이 필요한 물품이 있습니다"></i>` : ""}
      </button>`;
    }).join("");

    return `<div class="overview-map physical-map"><div class="overview-grid"></div>
      ${buildRoomZones()}<div class="sim-floor-outline"></div>${fixtures}${partitions}${buildGlassPartitions()}${buildRouteSvg()}${storageNodes}
      ${buildRobotMarker()}
      <div class="sim-axis sim-axis-x">X −7m ↔ +7m</div><div class="sim-axis sim-axis-y">Y −10m ↔ +16m</div>
      <div class="overview-map-title"><b>ISAAC LAB · TOP VIEW 1:1</b><span>USD ${_isaacMap.source.asset_sha256.slice(0, 10)} · ${getCatalogSummary()} · LOCATION MAP</span></div>
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
    updateRobotSyncBadge();
    updateRouteProgressBadge();
  }

  // 5. 물체 선택 및 사이드 인스펙터 패널 갱신
  function selectObjectById(sceneObjectId) {
    const vObj = VIRTUAL_LAB_OBJECTS.find((o) => o.sceneObjectId === sceneObjectId);
    if (!vObj) return;

    _selectedVirtualObj = vObj;
    _selectedStorageLocation = null;
    _matchedItem = findMatchingItem(vObj);
    if (_routeActive && Number(_routeItemId) !== Number(_matchedItem?.id)) _routeActive = false;

    renderLabCanvas();
    updateInspectorPanel();
  }

  function selectStorageLocation(location, preferredItemId = null) {
    const storage = _storageLocationMap.get(location);
    if (!storage) return;
    const items = getStorageItems(location);
    const matched = preferredItemId === null
      ? null
      : (items.find((item) => Number(item.id) === Number(preferredItemId)) || null);
    const dbBinding = matched ? findBindingEntryForItem(matched.id) : null;
    const meta = LOCATION_META[location] || { name: location };
    _selectedStorageLocation = location;
    _matchedItem = matched;
    if (_routeActive && Number(_routeItemId) !== Number(_matchedItem?.id)) _routeActive = false;
    _selectedVirtualObj = {
      sceneObjectId: dbBinding ? dbBinding[0] : `storage:${location}`,
      label: storage.shelf_code || "STORAGE",
      displayNameFallback: meta.name,
      category: matched ? matched.category : "INVENTORY",
      room: location,
      zoneTag: storage.shelf_code || location,
      description: `${meta.name}입니다. 아래 목록에서 보관 물품을 선택하면 재고와 선반 위치를 확인할 수 있습니다.`
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
    const infoGridEl = document.querySelector(".inspector-info-grid");

    if (!_selectedVirtualObj) return;

    const matched = _matchedItem;
    const isLocationOverview = Boolean(_selectedStorageLocation && !matched);
    const locationMeta = LOCATION_META[_selectedStorageLocation || _selectedVirtualObj.room] || { name: _selectedVirtualObj.room };
    const itemName = matched ? matched.name : _selectedVirtualObj.displayNameFallback;
    const category = matched ? matched.category : _selectedVirtualObj.category;
    const room = matched ? matched.location : _selectedVirtualObj.room;
    const stockStr = matched ? `${matched.available_qty} / ${matched.total_qty} ${matched.unit || "개"}` : "물품을 선택해 확인";
    const statusKey = matched ? computeStockStatus(matched) : "AVAILABLE";
    const statusLabel = STOCK_STATUS_LABEL[statusKey] || statusKey;
    const storage = matched ? (matched.storage_condition || "실온") : "실온";
    const expires = matched ? (matched.expires_at || "해당 없음") : "해당 없음";
    const bindingEntry = matched ? findBindingEntryForItem(matched.id) : null;
    const itemBinding = bindingEntry ? bindingEntry[1] : null;
    const locationMap = _selectedStorageLocation
      ? _storageLocationMap.get(_selectedStorageLocation)
      : _isaacObjectMap.get(_selectedVirtualObj.sceneObjectId);
    const isaacPosition = locationMap && locationMap.bbox ? locationMap.bbox.center : null;
    const robotTarget = Number.isFinite(itemBinding?.nav_x) && Number.isFinite(itemBinding?.nav_y)
      ? [itemBinding.nav_x, itemBinding.nav_y]
      : (locationMap ? locationMap.robot_target : null);
    const shelfPosition = formatShelfPosition(itemBinding, locationMap?.shelf_code || "미지정");
    const parentItem = matched?.storage_parent_item_id ? _itemsMap.get(matched.storage_parent_item_id) : null;
    const containedItems = matched && matched.is_rentable === false ? getContainedItems(matched.id) : [];

    if (infoGridEl) {
      infoGridEl.dataset.mode = isLocationOverview ? "location" : "item";
      const categoryLabel = infoGridEl.querySelector('.info-label[data-field="category"]');
      const statusLabelEl = infoGridEl.querySelector('.info-label[data-field="status"]');
      const shelfLabelEl = infoGridEl.querySelector('.info-label[data-field="shelf"]');
      if (categoryLabel) categoryLabel.textContent = isLocationOverview ? "장소 유형" : "분류";
      if (statusLabelEl) statusLabelEl.textContent = isLocationOverview ? "DB 상태" : "재고 상태";
      if (shelfLabelEl) shelfLabelEl.textContent = isLocationOverview ? "장소 코드" : "보관 위치코드";
    }

    if (titleEl) titleEl.innerText = isLocationOverview ? locationMeta.name : itemName;
    if (roomEl) roomEl.innerText = isLocationOverview
      ? `보관 구역 · ${_selectedVirtualObj.zoneTag}`
      : `${locationMeta.name} · ${shelfPosition}`;
    if (categoryEl) categoryEl.innerText = isLocationOverview ? "보관 구역" : category;
    if (stockEl) stockEl.innerText = stockStr;
    if (statusEl) statusEl.innerText = isLocationOverview
      ? (_catalogLoadState === "ready" ? "Supabase 실시간 연결" : "DB 연결 확인 필요")
      : statusLabel;
    if (storageEl) storageEl.innerText = isLocationOverview ? "물품별 보관조건 확인" : storage;
    if (expiresEl) expiresEl.innerText = isLocationOverview ? "물품별 유효기간 확인" : expires;
    if (shelfCodeEl) shelfCodeEl.innerText = shelfPosition;
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
    if (descEl) {
      if (isLocationOverview) {
        descEl.innerText = _selectedVirtualObj.description;
      } else if (parentItem) {
        descEl.innerText = `${parentItem.name} 내부 · ${matched.storage_position || "세부 위치 미지정"}`;
      } else if (containedItems.length > 0) {
        descEl.innerText = `${_selectedVirtualObj.description} 내부 보관 물품이 DB에 연결되어 있습니다.`;
      } else {
        descEl.innerText = itemBinding?.location_detail || _selectedVirtualObj.description;
      }
    }

    // 해당 물품에 대한 사용자 예약 건이 있는지 확인
    const userReservation = matched ? _activeUserLoans.find((l) => l.item_id === matched.id && l.status === "예약중") : null;
    const userActiveLoan = matched ? _activeUserLoans.find((l) => l.item_id === matched.id && l.status === "대여중") : null;
    const isConsumable = matched && window.LabBotRentals && window.LabBotRentals.isConsumable(matched);

    let actionBtnsHtml = "";
    if (containedItems.length > 0) {
      actionBtnsHtml += `<div class="storage-inventory-list"><strong>${escapeHtml(itemName)} 내부 보관 물품</strong><div>`;
      actionBtnsHtml += containedItems.map((item) => `<button type="button" class="storage-inventory-item" data-storage-item-id="${item.id}">
        <span>${escapeHtml(item.name)}</span><small>${escapeHtml(item.category || item.item_type || "미분류")} · ${escapeHtml(item.storage_position || "위치 미지정")}<br>재고 ${item.available_qty}/${item.total_qty} ${escapeHtml(item.unit || "개")}</small>
      </button>`).join("");
      actionBtnsHtml += `</div></div>`;
    }
    if (_selectedStorageLocation) {
      const storageItems = getStorageItems(_selectedStorageLocation);
      if (matched) {
        actionBtnsHtml += `<button type="button" class="location-overview-back" id="btnLocationOverview">← ${escapeHtml(locationMeta.name)} 전체 보기</button>`;
      }
      actionBtnsHtml += `<div class="storage-inventory-list"><strong>${escapeHtml(locationMeta.name)} 보관 물품</strong><div>`;
      actionBtnsHtml += storageItems.map((item) => {
        const status = computeStockStatus(item);
        const itemBindingEntry = findBindingEntryForItem(item.id);
        const itemBinding = itemBindingEntry ? itemBindingEntry[1] : null;
        const shelfLabel = formatShelfPosition(itemBinding, _storageLocationMap.get(_selectedStorageLocation)?.shelf_code || "미지정");
        return `<button type="button" class="storage-inventory-item ${_matchedItem && _matchedItem.id === item.id ? "is-selected" : ""}" data-storage-item-id="${item.id}">
          <span>${escapeHtml(item.name)}</span><small>${escapeHtml(item.category || item.item_type || "미분류")} · ${escapeHtml(shelfLabel)}<br>${escapeHtml(STOCK_STATUS_LABEL[status] || status)} · ${item.available_qty}/${item.total_qty} ${escapeHtml(item.unit || "개")}</small>
        </button>`;
      }).join("");
      actionBtnsHtml += `</div></div>`;
    }

    if (!matched) {
      actionBtnsHtml += "";
    } else if (matched.is_rentable === false) {
      actionBtnsHtml += `
        <button class="btn-virtual-action" style="background:var(--surface-2); color:var(--text-faint); cursor:not-allowed;" disabled>
          고정 보관 설비 · 대여 불가
        </button>
      `;
    } else if (userReservation) {
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
        ${_routeActive ? "경로 안내 숨기기" : "로봇 이동 경로 보기"}
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

      const overviewBtn = document.getElementById("btnLocationOverview");
      if (overviewBtn) overviewBtn.addEventListener("click", () => selectStorageLocation(_selectedStorageLocation));

      actionsEl.querySelectorAll("[data-storage-item-id]").forEach((button) => {
        button.addEventListener("click", () => selectStorageLocation(_selectedStorageLocation, Number(button.getAttribute("data-storage-item-id"))));
      });
    }
  }

  async function beginRobotGuide(loan, { notify = false } = {}) {
    if (!_matchedItem || !loan) return null;

    _routeActive = true;
    _routeItemId = _matchedItem.id;
    _currentFilterRoom = "all";
    renderRoomTabs();
    renderLabCanvas();
    updateInspectorPanel();

    try {
      if (!window.LabBotRobotConsole?.startRobotGuide) {
        throw new Error("로봇 안내 API가 준비되지 않았습니다.");
      }
      const mode = window.LabBotRentals?.isConsumable?.(_matchedItem) ? "use" : "pickup";
      const result = await LabBotRobotConsole.startRobotGuide({
        loanId: loan.id,
        item: _matchedItem,
        mode,
        targetMode: "sim"
      });
      _guideStatus = result || { status: "preview" };
      refreshRouteOverlay();

      if (notify && window.LabBotToast) {
        const message = result?.status === "navigating"
          ? "로봇을 따라가세요. 실시간 위치와 남은 경로를 표시합니다."
          : result?.status === "arrived"
            ? "로봇이 물품 선반 앞에 도착했습니다."
            : "경로를 표시했습니다. 로봇 주행 준비 상태를 확인하세요.";
        LabBotToast.show(message, "info");
      }
      return result;
    } catch (error) {
      console.info("[VirtualLab] Guide unavailable, keeping route preview:", error);
      _guideStatus = { status: "preview", message: error.message };
      refreshRouteOverlay();
      if (notify && window.LabBotToast) {
        LabBotToast.show("계획 경로를 표시했습니다. Isaac Sim을 켜면 RZ 위치가 실시간으로 연결됩니다.", "info");
      }
      return null;
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
    const reservedItem = _matchedItem;

    try {
      let loan = null;
      if (window.LabBotRentals) {
        loan = await LabBotRentals.reserveItem(reservedItem, session, "manual");
      }
      await loadDbItems();
      await loadUserLoans();
      focusItemById(reservedItem.id);
      const guideResult = loan ? await beginRobotGuide(loan) : null;
      if (window.LabBotToast) {
        const message = guideResult?.status === "navigating"
          ? `[${reservedItem.name}] 예약 완료. 로봇을 따라가세요.`
          : `[${reservedItem.name}] 예약 완료. 선반까지의 계획 경로를 표시합니다.`;
        LabBotToast.show(message, "success");
      }
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
  async function toggleRouteGuide() {
    if (_routeActive) {
      _routeActive = false;
      renderLabCanvas();
      updateInspectorPanel();
      if (window.LabBotToast) LabBotToast.show("경로 표시를 해제했습니다.", "info");
      return;
    }

    const reservation = _matchedItem
      ? _activeUserLoans.find((loan) => Number(loan.item_id) === Number(_matchedItem.id) && loan.status === "예약중")
      : null;
    if (reservation) {
      await beginRobotGuide(reservation, { notify: true });
      return;
    }

    _routeActive = true;
    _routeItemId = _matchedItem?.id || null;
    _currentFilterRoom = "all";
    _guideStatus = { status: "preview" };
    renderRoomTabs();
    renderLabCanvas();
    updateInspectorPanel();
    if (window.LabBotToast) {
      LabBotToast.show("현재 RZ 위치에서 선반 앞까지의 계획 경로를 표시합니다.", "info");
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

    _currentFilterRoom = "all";
    renderRoomTabs();
    selectStorageLocation(resolveStorageLocation(item), item.id);
    if (window.LabBotToast) LabBotToast.show(`가상 실험실에서 [${item.name}] 보관 위치를 찾았습니다!`, "info");
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

  window.addEventListener("pagehide", () => {
    if (_robotTelemetryTimer) window.clearTimeout(_robotTelemetryTimer);
  });
  window.addEventListener("DOMContentLoaded", initVirtualLab);
})();
