"""Export the authoritative Isaac USD top view for the LabBot web digital twin.

This script reads the built USD directly. It never estimates coordinates from the
builder source and never writes inventory quantities or QR secrets. Run it after
changing the lab asset, object bindings, guide targets, or QR zone anchors.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pxr import Usd, UsdGeom


PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parents[1]
ASSET_PATH = PROJECT_DIR / "assets" / "labkeeper_lab_v2.usda"
SCENE_DIR = PROJECT_DIR / "scene"
OUTPUT_PATH = REPO_ROOT / "web" / "data" / "isaac_lab_map.json"


FIXTURE_SPECS = (
    ("/World/CleanCorridor", "Robot Aisle", "aisle"),
    ("/World/MainBench/IslandWest", "Island West", "bench"),
    ("/World/MainBench/IslandEast", "Island East", "bench"),
    ("/World/MainBench/WestWallBench", "West Wall Bench", "bench"),
    ("/World/MainBench/EastWallBench", "East Wall Bench", "bench"),
    ("/World/West/InstrumentBench1", "Instrument Bench 1", "equipment"),
    ("/World/West/InstrumentBench2", "Instrument Bench 2", "equipment"),
    ("/World/West/Cell_BSC_Base", "BSC", "equipment"),
    ("/World/West/CO2Incubator", "CO2 Incubator", "equipment"),
    ("/World/East/Consumables_Shelf", "Consumables 1", "storage"),
    ("/World/East/Consumables_Shelf_1", "Consumables 2", "storage"),
    ("/World/East/Fridge_4C", "4C Fridge", "cold"),
    ("/World/East/Freezer_80C_1", "-80C Freezer 1", "cold"),
    ("/World/East/Freezer_80C_2", "-80C Freezer 2", "cold"),
    ("/World/North/Reagent_Desk", "Reagent Desk", "reagent"),
    ("/World/Safety/FlammableCabinet", "Flammable Cabinet", "safety"),
    ("/World/Safety/PPECabinet", "PPE Cabinet", "safety"),
    ("/World/Safety/FireExtinguisher", "Fire Extinguisher", "safety"),
    ("/World/Safety/SpillKit", "Spill Kit", "safety"),
    ("/World/Safety/EyeWash", "Eye Wash", "safety"),
    ("/World/RentalWing/CenterLane", "Entry Aisle", "aisle"),
    ("/World/RentalWing/WestPickupShelf", "Entry Shelf West", "storage"),
    ("/World/RentalWing/EastPickupShelf", "Entry Shelf East", "storage"),
    ("/World/RentalWing/WestWallStorage_0", "Entry Storage West 1", "storage"),
    ("/World/RentalWing/WestWallStorage_1", "Entry Storage West 2", "storage"),
    ("/World/RentalWing/WestWallStorage_2", "Entry Storage West 3", "storage"),
    ("/World/RentalWing/EastWallStorage_0", "Entry Storage East 1", "storage"),
    ("/World/RentalWing/EastWallStorage_1", "Entry Storage East 2", "storage"),
    ("/World/RentalWing/EastWallStorage_2", "Entry Storage East 3", "storage"),
    ("/World/RentalWing/PackingBench", "Packing Bench", "bench"),
    ("/World/RentalWing/ReturnDesk", "Service Desk", "bench"),
    ("/World/RentalWing/KioskBase", "Guide Kiosk", "equipment"),
    ("/World/RentalWing/DockPad", "Robot Dock", "dock"),
)

FLOOR_PRIM_PATHS = ("/World/LabFloor", "/World/RentalWing/Floor")
ARCHITECTURE_ROOT_PATHS = ("/World/Architecture", "/World/RentalWing")
ARCHITECTURE_NAME_TOKENS = (
    "Wall", "Divider", "RoomFront", "Jamb", "SecurityGlass", "DoorRail",
)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def rounded(value: float) -> float:
    return round(float(value), 4)


def world_box(stage: Usd.Stage, cache: UsdGeom.BBoxCache, prim_path: str):
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid() or not prim.IsActive():
        return None
    aligned = cache.ComputeWorldBound(prim).ComputeAlignedRange()
    minimum = aligned.GetMin()
    maximum = aligned.GetMax()
    if any(abs(float(v)) > 1_000_000 for v in (*minimum, *maximum)):
        return None
    return {
        "min": [rounded(minimum[0]), rounded(minimum[1]), rounded(minimum[2])],
        "max": [rounded(maximum[0]), rounded(maximum[1]), rounded(maximum[2])],
        "center": [
            rounded((minimum[0] + maximum[0]) / 2),
            rounded((minimum[1] + maximum[1]) / 2),
            rounded((minimum[2] + maximum[2]) / 2),
        ],
        "size": [
            rounded(maximum[0] - minimum[0]),
            rounded(maximum[1] - minimum[1]),
            rounded(maximum[2] - minimum[2]),
        ],
    }


def combined_world_box(stage: Usd.Stage, cache: UsdGeom.BBoxCache, prim_paths):
    boxes = [world_box(stage, cache, prim_path) for prim_path in prim_paths]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None

    minimum = [min(box["min"][axis] for box in boxes) for axis in range(3)]
    maximum = [max(box["max"][axis] for box in boxes) for axis in range(3)]
    return {
        "min": minimum,
        "max": maximum,
        "center": [rounded((minimum[axis] + maximum[axis]) / 2) for axis in range(3)],
        "size": [rounded(maximum[axis] - minimum[axis]) for axis in range(3)],
    }


def export_map():
    stage = Usd.Stage.Open(str(ASSET_PATH))
    if stage is None:
        raise RuntimeError(f"Could not open Isaac asset: {ASSET_PATH}")
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])

    floor_box = combined_world_box(stage, cache, FLOOR_PRIM_PATHS)
    if floor_box is None:
        raise RuntimeError("No configured laboratory floor has valid world bounds")

    fixtures = []
    missing_fixtures = []
    for prim_path, label, fixture_type in FIXTURE_SPECS:
        bbox = world_box(stage, cache, prim_path)
        if bbox is None:
            missing_fixtures.append(prim_path)
            continue
        fixtures.append({"prim_path": prim_path, "label": label, "type": fixture_type, "bbox": bbox})

    architecture = []
    seen_architecture_paths = set()
    for root_path in ARCHITECTURE_ROOT_PATHS:
        architecture_root = stage.GetPrimAtPath(root_path)
        if not architecture_root or not architecture_root.IsValid():
            continue
        for prim in Usd.PrimRange(architecture_root):
            if prim == architecture_root or not prim.IsA(UsdGeom.Gprim):
                continue
            name = prim.GetName()
            prim_path = str(prim.GetPath())
            if prim_path in seen_architecture_paths or not any(token in name for token in ARCHITECTURE_NAME_TOKENS):
                continue
            bbox = world_box(stage, cache, prim_path)
            if bbox is not None:
                seen_architecture_paths.add(prim_path)
                architecture.append({"prim_path": prim_path, "label": name, "type": "wall", "bbox": bbox})

    bindings_doc = load_json(SCENE_DIR / "object_bindings.json")
    guide_doc = load_json(SCENE_DIR / "guide_targets.json")
    anchors_doc = load_json(SCENE_DIR / "qr_anchors.json")
    guide_by_object = {row["scene_object_id"]: row for row in guide_doc.get("targets", [])}

    mapped_objects = []
    missing_bindings = []
    for binding in bindings_doc.get("bindings", []):
        bbox = world_box(stage, cache, binding["prim_path"])
        if bbox is None:
            missing_bindings.append(binding)
            continue
        guide = guide_by_object.get(binding["scene_object_id"], {})
        mapped_objects.append({
            **binding,
            "bbox": bbox,
            "shelf_code": guide.get("shelf_code"),
            "shelf_row": guide.get("shelf_row"),
            "shelf_slot": guide.get("shelf_slot"),
            "location_detail": guide.get("location_detail"),
            "robot_target": guide.get("target"),
            "route": guide.get("route", []),
        })

    storage_locations = []
    missing_storage_fixtures = []
    for location_name, location in guide_doc.get("location_defaults", {}).items():
        fixture_prim_path = location.get("fixture_prim_path")
        bbox = world_box(stage, cache, fixture_prim_path) if fixture_prim_path else None
        if bbox is None:
            missing_storage_fixtures.append({"location": location_name, "prim_path": fixture_prim_path})
            continue
        storage_locations.append({
            "location": location_name,
            "fixture_prim_path": fixture_prim_path,
            "bbox": bbox,
            "shelf_code": location.get("shelf_code"),
            "zone_type": location.get("zone_type"),
            "access_level": location.get("access_level"),
            "robot_target": location.get("target"),
            "route": location.get("route", []),
        })

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "asset": str(ASSET_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
            "asset_sha256": hashlib.sha256(ASSET_PATH.read_bytes()).hexdigest(),
            "coordinate_system": "Isaac world XY in meters; portrait web top view maps X left-to-right and Y bottom-to-top",
        },
        "world": {
            "min_x": floor_box["min"][0],
            "max_x": floor_box["max"][0],
            "min_y": floor_box["min"][1],
            "max_y": floor_box["max"][1],
            "floor_bbox": floor_box,
        },
        "fixtures": fixtures,
        "architecture": architecture,
        "zones": anchors_doc.get("zones", []),
        "track_points": anchors_doc.get("track_points", []),
        "mapped_objects": mapped_objects,
        "storage_locations": storage_locations,
        "location_defaults": guide_doc.get("location_defaults", {}),
        "category_defaults": guide_doc.get("category_defaults", {}),
        "validation": {
            "missing_fixture_paths": missing_fixtures,
            "missing_object_bindings": missing_bindings,
            "missing_storage_fixtures": missing_storage_fixtures,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(
        "ISAAC_WEB_MAP_EXPORT_OK "
        f"fixtures={len(fixtures)} architecture={len(architecture)} "
        f"objects={len(mapped_objects)} storage={len(storage_locations)} output={OUTPUT_PATH}"
    )
    if missing_fixtures or missing_bindings:
        print(f"WARN missing_fixtures={len(missing_fixtures)} missing_bindings={len(missing_bindings)}")


if __name__ == "__main__":
    export_map()
