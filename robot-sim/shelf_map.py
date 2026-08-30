"""물품이 어느 선반에 있고, 그 선반이 어디인지.

왜 필요한가
----------
대여 요청이 들어오면 로봇이 그 물품 앞으로 가야 하는데, "물품 42번이 실제 방의
어디인가"를 아무도 정해두지 않았다. 아이작 심 쪽에는 virtual_lab_objects 에
nav_x/nav_y 가 있지만 그건 가상 실험실 좌표라 실물 거실과 아무 상관이 없다.

그래서 실물 쪽 배치를 여기서 정한다. 순찰 경로의 세 꼭짓점을 선반으로 삼고,
물품 99개를 33개씩 나눠 붙인다. 실제 선반이 아니라 임의 지정이지만, 대여
흐름을 끝까지 굴려보려면 어딘가는 정해져 있어야 한다.

왜 ID 범위가 아니라 정렬 순서인가
------------------------------
물품 ID 가 1~99 로 연속이 아니다(32, 35, 41 … 처럼 띄엄띄엄 있다). "1~33번은
A 선반" 같은 범위 규칙을 쓰면 어떤 선반은 5개, 어떤 선반은 60개가 된다.
ID 를 오름차순으로 늘어놓고 3등분해야 33개씩 고르게 나뉜다.

배치를 파일로 남기는 이유
---------------------
규칙만 코드에 두면 물품이 하나 추가될 때마다 기존 물품의 선반이 통째로 바뀐다
(3등분 경계가 밀리기 때문이다). 대여 이력과 실제 배치가 어긋나므로, 한 번 정한
배치는 파일에 적어두고 새 물품만 덧붙인다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / "state"
ASSIGN_PATH = STATE_DIR / "shelf_assignment.json"

# 순찰 경로의 꼭짓점 중 출발점(0,0)을 뺀 세 곳을 선반으로 쓴다. 출발점은
# 로봇이 대기하는 자리라 물품을 두지 않는다.
DEFAULT_SHELVES = [
    {"code": "A", "name": "선반 A", "waypoint": 1},
    {"code": "B", "name": "선반 B", "waypoint": 2},
    {"code": "C", "name": "선반 C", "waypoint": 3},
]


def shelves_from_map(patrol_map):
    """순찰 지도의 꼭짓점 좌표를 선반 좌표로 옮긴다.

    선반 좌표를 따로 적지 않고 순찰 경로에서 끌어오는 이유는, 방 크기를 바꿔
    경로를 줄이면(200x110 -> 190x100) 선반도 같이 따라와야 하기 때문이다.
    두 군데에 적어두면 반드시 한쪽만 고치게 된다.
    """
    wps = (patrol_map or {}).get("waypoints") or []
    out = []
    for shelf in (patrol_map or {}).get("shelves") or DEFAULT_SHELVES:
        idx = shelf.get("waypoint")
        if idx is None or idx >= len(wps):
            continue
        wp = wps[idx]
        out.append({
            "code": shelf["code"],
            "name": shelf.get("name") or shelf["code"],
            "x_cm": wp.get("x_cm", 0),
            "y_cm": wp.get("y_cm", 0),
            "waypoint": idx,
            "waypoint_name": wp.get("name") or str(idx),
        })
    return out


def load_assignment():
    try:
        return json.loads(ASSIGN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}, "rule": "", "generated_at": None}


def save_assignment(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ASSIGN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return data


def build_assignment(item_ids, shelf_codes, keep_existing=True):
    """물품을 선반에 고르게 나눈다. 이미 배치된 물품은 그대로 둔다.

    keep_existing 이 핵심이다. 3등분은 전체 개수에 따라 경계가 움직이므로,
    물품 하나가 추가될 때 다시 계산하면 멀쩡히 A 선반에 있던 물품이 B 로
    바뀐다. 실제 물건은 그대로인데 시스템만 바뀌는 것이라 대여가 어긋난다.
    """
    prev = load_assignment().get("items", {}) if keep_existing else {}
    assigned = {k: v for k, v in prev.items()
                if int(k) in set(item_ids) and v in shelf_codes}

    # 이미 각 선반에 몇 개가 있는지 세고, 새 물품은 제일 빈 선반부터 채운다.
    counts = {c: 0 for c in shelf_codes}
    for code in assigned.values():
        counts[code] += 1

    for item_id in sorted(item_ids):
        key = str(item_id)
        if key in assigned:
            continue
        code = min(shelf_codes, key=lambda c: (counts[c], c))
        assigned[key] = code
        counts[code] += 1

    return save_assignment({
        "rule": "물품 ID 오름차순으로 선반에 고르게 배분. 기존 배치는 유지하고 새 물품만 채운다.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": counts,
        "items": assigned,
    })


def shelf_of(item_id):
    """이 물품이 어느 선반인가. 배치가 없으면 None."""
    return load_assignment().get("items", {}).get(str(int(item_id)))


def locate(item_id, patrol_map):
    """물품의 선반과 좌표. 대여 요청이 오면 이 좌표로 간다."""
    code = shelf_of(item_id)
    if not code:
        return None
    for shelf in shelves_from_map(patrol_map):
        if shelf["code"] == code:
            return shelf
    return None


def summary(patrol_map):
    """선반별로 몇 개가 있는지. 웹에서 배치를 확인할 때 쓴다."""
    data = load_assignment()
    shelves = shelves_from_map(patrol_map)
    counts = data.get("counts") or {}
    if not counts:
        counts = {}
        for code in data.get("items", {}).values():
            counts[code] = counts.get(code, 0) + 1
    return {
        "rule": data.get("rule"),
        "generated_at": data.get("generated_at"),
        "total": len(data.get("items", {})),
        "shelves": [dict(s, item_count=counts.get(s["code"], 0)) for s in shelves],
    }
