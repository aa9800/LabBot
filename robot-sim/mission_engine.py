"""라즈봇 내부 물품 위치 캐시와 고수준 안내 임무 상태 관리자.

웹은 item_id와 request_id만 보낸다. 물품명·선반·좌표·실물 주행 경로는 로봇의
로컬 캐시에서 해석하며, 한 임무가 끝난 뒤 다음 임무는 홈으로 복귀하지 않고 현재
위치를 출발점으로 삼는다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


class ItemLocationCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._document = {"schema_version": 1, "revision": "empty", "items": {}}
        self.reload()

    def reload(self):
        with self._lock:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded.get("items"), dict):
                    raise ValueError("items는 객체여야 합니다.")
                self._document = loaded
            except FileNotFoundError:
                pass
            return self.status()

    def resolve(self, item_id):
        with self._lock:
            item = self._document["items"].get(str(int(item_id)))
            return dict(item) if item else None

    def replace(self, items, revision=None):
        """PC 중계기가 DB의 공개 위치 필드만 동기화한다. QR 비밀값은 받지 않는다."""
        if not isinstance(items, list):
            raise ValueError("items는 배열이어야 합니다.")
        normalized = {}
        with self._lock:
            existing = self._document.get("items", {})
            for raw in items:
                item_id = int(raw["item_id"])
                old = existing.get(str(item_id), {})
                physical_route = raw.get("physical_route") or old.get("physical_route") or {
                    "status": "calibration_required",
                    "segments": [],
                }
                normalized[str(item_id)] = {
                    "item_id": item_id,
                    "item_name": str(raw.get("item_name") or f"물품 {item_id}"),
                    "category": str(raw.get("category") or ""),
                    "room": str(raw.get("room") or raw.get("location") or ""),
                    "scene_object_id": str(raw.get("scene_object_id") or ""),
                    "shelf_code": str(raw.get("shelf_code") or ""),
                    "shelf_row": raw.get("shelf_row"),
                    "shelf_slot": raw.get("shelf_slot"),
                    "location_detail": str(raw.get("location_detail") or ""),
                    "nav_x": raw.get("nav_x"),
                    "nav_y": raw.get("nav_y"),
                    "nav_heading": raw.get("nav_heading", 0),
                    "physical_route": physical_route,
                }
            document = {
                "schema_version": 1,
                "revision": str(revision or int(time.time())),
                "updated_at": time.time(),
                "items": normalized,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temp_path, self.path)
            self._document = document
            return self.status()

    def status(self):
        with self._lock:
            return {
                "revision": self._document.get("revision", "unknown"),
                "updated_at": self._document.get("updated_at"),
                "item_count": len(self._document.get("items", {})),
            }


class MissionEngine:
    TERMINAL = {"completed", "cancelled", "failed"}

    def __init__(self, location_cache: ItemLocationCache, supported_route_controllers=None):
        self.location_cache = location_cache
        self.supported_route_controllers = frozenset(supported_route_controllers or ())
        self._lock = threading.RLock()
        self._active = None
        self._last_request_id = None
        self._last_result = None
        self._current_location_key = "dock"

    def start(self, *, request_id, item_id, mission_type="pickup"):
        request_id = str(request_id or "").strip()
        if not request_id:
            raise ValueError("request_id가 필요합니다.")
        mission_type = str(mission_type or "pickup")
        if mission_type not in {"pickup", "return", "use"}:
            raise ValueError("mission_type은 pickup, return, use 중 하나여야 합니다.")
        item = self.location_cache.resolve(item_id)
        if item is None:
            raise KeyError(f"로봇 로컬 위치 캐시에 item_id={item_id}가 없습니다.")

        with self._lock:
            if request_id == self._last_request_id and self._last_result is not None:
                return dict(self._last_result)
            previous = self._active
            route = item.get("physical_route") or {}
            route_calibrated = route.get("status") == "verified" and bool(route.get("segments"))
            route_controller = str(route.get("controller") or "").strip()
            executor_available = route_controller in self.supported_route_controllers
            route_ready = route_calibrated and executor_available
            if not route_calibrated:
                status = "awaiting_route_calibration"
                message = "물품 위치는 확인됐지만 실물 주행 경로 캘리브레이션이 필요합니다."
            elif not executor_available:
                status = "awaiting_route_executor"
                message = (
                    f"경로는 검증됐지만 실행기 '{route_controller or '미지정'}'가 "
                    "실물 로봇에 연결되지 않아 안전 정지합니다."
                )
            else:
                status = "navigating"
                message = "로봇을 따라가세요."
            self._active = {
                "request_id": request_id,
                "task_id": request_id,
                "item_id": int(item_id),
                "mission_type": mission_type,
                "status": status,
                "started_at": time.time(),
                "departure_location": self._current_location_key,
                "direct_from_previous": self._current_location_key != "dock",
                "replaced_request_id": previous.get("request_id") if previous else None,
                **{key: value for key, value in item.items() if key != "physical_route"},
                "physical_route": route,
                "route_controller": route_controller or None,
                "route_executor_available": executor_available,
                "message": message,
            }
            self._last_request_id = request_id
            self._last_result = dict(self._active)
            return dict(self._active)

    def finish(self, status="completed"):
        if status not in self.TERMINAL:
            raise ValueError("종료 상태가 올바르지 않습니다.")
        with self._lock:
            if not self._active:
                return {"status": "idle", "current_location": self._current_location_key}
            result = dict(self._active)
            result["status"] = status
            result["finished_at"] = time.time()
            if status == "completed":
                self._current_location_key = result.get("shelf_code") or str(result["item_id"])
            result["current_location"] = self._current_location_key
            self._active = None
            self._last_result = dict(result)
            return result

    def status(self):
        with self._lock:
            if not self._active:
                return {
                    "status": "idle",
                    "current_location": self._current_location_key,
                    "location_cache": self.location_cache.status(),
                }
            return {**self._active, "location_cache": self.location_cache.status()}

    def should_drive(self):
        with self._lock:
            return bool(self._active and self._active.get("status") == "navigating")
