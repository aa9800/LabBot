"""LabBot 실감형 대학 생명공학 연구실 자율주행 순찰 시뮬레이터 (NVIDIA Isaac Sim 4.5/6.0).

한국 대학 생명공학 연구실 3D 디지털 트윈 환경에서 Yahboom Raspbot 로봇이 9개 보관 구역을
순찰하며, 실시간 3D FPV 카메라 스트리밍, 라인센서 트래킹, 초음파 장애물 감지,
카메라 Pan/Tilt 서보 조절, QR 체크포인트 스캔 및 admin.html 웹 제어 연동을 수행한다.
"""
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import cv2

# Isaac Sim Python venv 환경 검증
try:
    from isaacsim.simulation_app import SimulationApp
except ImportError:
    print("[LabBot] Isaac Sim Python 환경이 필요합니다.")
    print('  실행 예: & "C:\\Users\\a9800\\isaac_clean\\venv\\Scripts\\python.exe" run_isaac.py')
    sys.exit(1)

_HEADLESS = os.environ.get("HEADLESS", "0").lower() in ("1", "true", "yes")
_WINDOW_WIDTH = int(os.environ.get("LABKEEPER_WINDOW_WIDTH", "1600"))
_WINDOW_HEIGHT = int(os.environ.get("LABKEEPER_WINDOW_HEIGHT", "900"))
simulation_app = SimulationApp({"headless": _HEADLESS, "width": _WINDOW_WIDTH, "height": _WINDOW_HEIGHT})

# LabBot 공통 모듈 경로 등록
_ISAAC_PROJ_DIR = os.path.dirname(os.path.abspath(__file__))
_ROBOT_SIM_ROOT = os.path.dirname(_ISAAC_PROJ_DIR)
_LABKEEPER_ROOT = os.path.dirname(_ROBOT_SIM_ROOT)
sys.path.insert(0, _LABKEEPER_ROOT)
sys.path.insert(0, _ROBOT_SIM_ROOT)
sys.path.insert(0, _ISAAC_PROJ_DIR)

import omni.usd
from isaacsim.core.api import World
from isaacsim.sensors.camera import Camera
from pxr import Gf, UsdGeom, UsdLux

import stream_server
from isaac_hal import IsaacHAL
from lab_world import (
    LAB_TRACK_POINTS_M,
    LAB_ZONES,
    build_lab_environment,
    get_all_checkpoints,
    resolve_guide_target,
)
from run_logger import JsonlRunLogger
from night_guard import NightGuardScheduler
from notify_supabase import fetch_items, report_safety_event
from raspbot_model import KinematicRaspbot, create_raspbot, load_robot_spec
from waypoint_controller import WaypointPatrolController
from render_quality import configure_rtx_quality

OBSTACLE_PATH = "/World/Obstacle"
TIME_STEP_S = 1.0 / 60.0
TELEMETRY_LOG_EVERY = 30
OBSTACLE_ALERT_COOLDOWN = 3.0
OBSTACLE_STOP_DISTANCE = 20.0
MANUAL_COMMAND_MAX_AGE_SECONDS = 3.0  # 실물(run_real.py)과 동일하게 맞춤 — 1초면 키보드 주행이 끊긴다
FPV_WIDTH = int(os.environ.get("LABKEEPER_FPV_WIDTH", "960"))
FPV_HEIGHT = int(os.environ.get("LABKEEPER_FPV_HEIGHT", "540"))
JPEG_QUALITY = max(65, min(95, int(os.environ.get("LABKEEPER_JPEG_QUALITY", "84"))))
STREAM_EVERY_N_TICKS = max(1, int(os.environ.get("LABKEEPER_STREAM_EVERY_N_TICKS", "1")))
LAB_PREVIEW_WIDTH = int(os.environ.get("LABKEEPER_PREVIEW_WIDTH", "1280"))
LAB_PREVIEW_HEIGHT = int(os.environ.get("LABKEEPER_PREVIEW_HEIGHT", "720"))
LAB_PREVIEW_EVERY_N_TICKS = max(15, int(os.environ.get("LABKEEPER_PREVIEW_EVERY_N_TICKS", "30")))
ISAAC_AUTO_PATROL_DEFAULT = os.environ.get("LABKEEPER_ISAAC_AUTO_PATROL", "1").lower() not in (
    "0", "false", "no"
)
ISAAC_PATROL_WAYPOINT_NAMES = (
    "대기 위치",
    "보안 게이트",
    "입구 좌측 진입",
    "입구 좌측 보급공간",
    "입구 중앙",
    "입구 우측 보급공간",
    "입구 우측 진입",
    "보안 게이트 복귀",
    "중앙 복도",
    "일반실험실",
    "서측 통로 진입",
    "서측 통로",
    "기기실-1",
    "기기실-2",
    "세포배양실",
    "시약보관실",
    "냉동보관실",
    "냉장보관실",
    "소모품보관실",
    "동측 통로",
    "동측 통로 복귀",
    "중앙 복도 복귀",
    "대기 위치 복귀",
)


def _isaac_patrol_map():
    """웹 좌표 순찰 패널이 바로 그릴 수 있는 cm 단위 Isaac 전용 경로."""
    waypoints = []
    for index, point in enumerate(LAB_TRACK_POINTS_M):
        name = (
            ISAAC_PATROL_WAYPOINT_NAMES[index]
            if index < len(ISAAC_PATROL_WAYPOINT_NAMES)
            else f"순찰 지점 {index}"
        )
        waypoints.append({
            "name": name,
            "marker": None,
            "x_cm": round(float(point[0]) * 100.0, 1),
            "y_cm": round(float(point[1]) * 100.0, 1),
        })
    return {
        "name": "Isaac 전체 연구실 자동순찰",
        "env": "isaac",
        "source": "isaac-sim",
        "units": "cm",
        "closed": True,
        "description": "입구 보급공간부터 실험실·보관실을 순회한 뒤 대기 위치로 복귀합니다.",
        "waypoints": waypoints,
    }


def _create_obstacle(stage):
    """실시간 동적 장애물 (실험실 트롤리/카트)."""
    if stage.GetPrimAtPath(OBSTACLE_PATH).IsValid():
        return
    prim = stage.DefinePrim(OBSTACLE_PATH, "Cube")
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(999.0, 999.0, -10.0))  # 기본 비활성 위치
    scale_op = xform.AddScaleOp()
    scale_op.Set(Gf.Vec3d(0.20, 0.20, 0.30))
    UsdGeom.Gprim(prim).GetDisplayColorAttr().Set([Gf.Vec3f(0.9, 0.2, 0.2)])
    return translate_op


def _compute_camera_quaternion(eye_pos, heading_rad, pan_deg=90, tilt_deg=90):
    """로봇 진행방향(heading)과 Pan/Tilt 서보 각도를 결합하여 FPV 카메라 쿼터니언을 생성한다."""
    # pan: 0(좌) -> 90(정면) -> 180(우)
    # tilt: 0(바닥/QR) -> 90(정면 수평) -> 180(상단선반/시약)
    rel_pan = math.radians(pan_deg - 90.0)
    # 기본 시야각을 전방 바닥과 작업대가 잘 보이도록 살짝(-6도) 숙임
    rel_tilt = math.radians(tilt_deg - 90.0 - 6.0)

    total_yaw = heading_rad - rel_pan
    total_pitch = rel_tilt

    fx = math.cos(total_yaw) * math.cos(total_pitch)
    fy = math.sin(total_yaw) * math.cos(total_pitch)
    fz = math.sin(total_pitch)

    eye_gf = Gf.Vec3d(float(eye_pos[0]), float(eye_pos[1]), float(eye_pos[2]))
    tgt_gf = Gf.Vec3d(float(eye_pos[0] + fx * 4.0), float(eye_pos[1] + fy * 4.0), float(eye_pos[2] + fz * 4.0))
    up_gf = Gf.Vec3d(0.0, 0.0, 1.0)

    mat = Gf.Matrix4d().SetLookAt(eye_gf, tgt_gf, up_gf)
    q = mat.GetInverse().ExtractRotation().GetQuat()
    return np.array([q.GetReal(), q.GetImaginary()[0], q.GetImaginary()[1], q.GetImaginary()[2]])


def _look_at_quaternion(eye_pos, target_pos):
    eye = Gf.Vec3d(*(float(v) for v in eye_pos))
    target = Gf.Vec3d(*(float(v) for v in target_pos))
    matrix = Gf.Matrix4d().SetLookAt(eye, target, Gf.Vec3d(0.0, 0.0, 1.0))
    quat = matrix.GetInverse().ExtractRotation().GetQuat()
    imaginary = quat.GetImaginary()
    return np.array([quat.GetReal(), imaginary[0], imaginary[1], imaginary[2]])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    quality_name, quality_config = configure_rtx_quality()
    print(
        f"[LabBot] RTX preset={quality_name} renderer={quality_config['render_mode']} "
        f"DLSS={quality_config['dlss_mode']} FPV={FPV_WIDTH}x{FPV_HEIGHT} JPEG={JPEG_QUALITY} "
        f"streamEvery={STREAM_EVERY_N_TICKS}tick"
    )

    log_dir = os.path.join(_ROBOT_SIM_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    run_log = JsonlRunLogger(log_dir, source="isaac")
    network_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="labbot-net")

    def report_event_async(*args, **kwargs):
        network_executor.submit(report_safety_event, *args, **kwargs)
    print(f"[LabBot] Isaac Sim run log: {run_log.path}")

    robot_spec = load_robot_spec()
    camera_spec = robot_spec["camera"]
    items = fetch_items()
    checkpoints = get_all_checkpoints()
    print(f"[LabBot] 9 Storage Zones loaded: {[c['name'] for c in checkpoints]}")

    world = World(stage_units_in_meters=1.0)

    # 1. 9개 구역 한국 대학 생명공학 연구실 디지털 트윈 구축
    stage = omni.usd.get_context().get_stage()
    dome = UsdLux.DomeLight.Define(stage, "/World/RootDomeLight")
    dome.CreateIntensityAttr(360.0)
    dome.CreateColorAttr(Gf.Vec3f(0.93, 0.96, 1.0))

    sun = UsdLux.DistantLight.Define(stage, "/World/RootSun")
    sun.CreateIntensityAttr(260.0)
    UsdGeom.Xformable(sun).AddRotateXOp().Set(-55.0)

    build_lab_environment(stage, items=items)
    _create_obstacle(stage)

    # 2. 로봇 FPV 실시간 3D 카메라 센서 정의
    cam_prim_path = "/World/FollowCamera"
    UsdGeom.Camera.Define(stage, cam_prim_path)
    cam = Camera(
        prim_path=cam_prim_path,
        # Camera는 name을 안 주면 전부 기본값 "camera"로 등록된다 — 카메라가 둘 이상이면
        # world.scene.add()에서 "name is not unique"로 죽는다. 반드시 서로 다른 이름을 준다.
        name="fpv_camera",
        # RTX 5070에서 소형 피펫/시약병/QR을 구분하되 AI 추론 지연은 제어한다.
        resolution=(FPV_WIDTH, FPV_HEIGHT),
        frequency=30,
    )
    world.scene.add(cam)

    # 웹 가상실험실 페이지용 별도 RTX 오버뷰. 로봇 FPV와 카메라 각도를 공유하지
    # 않으므로 사용자가 조종 중이어도 실험실 전체 배치 프리뷰가 흔들리지 않는다.
    overview_cam_path = "/World/WebLabOverviewCamera"
    UsdGeom.Camera.Define(stage, overview_cam_path)
    overview_cam = Camera(
        prim_path=overview_cam_path,
        name="lab_overview_camera",
        resolution=(LAB_PREVIEW_WIDTH, LAB_PREVIEW_HEIGHT),
        frequency=5,
    )
    world.scene.add(overview_cam)

    # 3. 실측 사양 기반 Yahboom Raspbot 4WD 모델 생성
    raspbot_path = create_raspbot(stage)
    raspbot = KinematicRaspbot(stage, raspbot_path)

    world.reset()

    start_x, start_y = LAB_TRACK_POINTS_M[0]
    next_x, next_y = LAB_TRACK_POINTS_M[1]
    heading = math.atan2(next_y - start_y, next_x - start_x)
    qz, qw = math.sin(heading / 2), math.cos(heading / 2)

    raspbot.set_world_poses(
        positions=np.array([[start_x, start_y, 0.0]]),
        orientations=np.array([[qw, 0.0, 0.0, qz]]),
    )
    cam.initialize()
    overview_cam.initialize()
    # 별도 대여/반납실 없이 실제 연구실 구역 전체를 한 프레임에 담는다.
    overview_eye = np.array([15.0, -15.0, 23.0])
    overview_target = np.array([0.0, 7.0, 0.55])
    overview_cam.set_world_pose(
        position=overview_eye,
        orientation=_look_at_quaternion(overview_eye, overview_target),
        camera_axes="usd",
    )
    for _ in range(5):
        world.step(render=True)

    hal = IsaacHAL(stage, raspbot, obstacle_prim_path=OBSTACLE_PATH, checkpoints=checkpoints, camera=cam)
    night_guard = NightGuardScheduler()

    # 4. 로컬 30 FPS 웹 스트림 서버 시작 (admin.html 연동)
    try:
        stream_server.start_stream_server(port=8080)
        print("[LabBot] Stream Server running on http://localhost:8080/stream")
    except OSError as e:
        # 예전에는 여기서 print만 하고 계속 진행했다. 그러면 이전 인스턴스가 8080을
        # 잡고 있을 때 새 창은 스트림 서버 없이 돌고, 웹 조이스틱은 죽은 이전
        # 프로세스를 조종하게 된다. 차라리 즉시 종료해서 원인을 드러낸다.
        print(f"[LabBot] 포트 8080을 열 수 없습니다: {e}")
        print("[LabBot] 이전 Isaac Sim 인스턴스가 아직 떠 있는지 확인하세요.")
        simulation_app.close()
        sys.exit(1)

    # 스트림 서버 콜백 연결 (수동 운전 / 서보 / 온디맨드 QR 스캔 / 실시간 텔레메트리)
    manual_override = {"active": False, "speed": 0.0, "turn": 0.0, "last_at": 0.0}
    # 실물 Raspbot의 경로 실행기와 무관한 Isaac 전용 자동순찰 스위치다.
    # 웹에서 auto 모드를 선택하면 켜지고, manual 모드에서는 수동 명령이 우선한다.
    auto_patrol = {
        "enabled": ISAAC_AUTO_PATROL_DEFAULT,
        "requested_laps": 0,
        "start_completed_laps": 0,
        "target_completed_laps": None,
        "repeat_minutes": 0,
        "next_run_at": None,
        "emergency_latched": False,
        "operator_hold": False,
        "mode": "patrol",
        "phase": "driving" if ISAAC_AUTO_PATROL_DEFAULT else "idle",
        "message": (
            "Isaac 전체 연구실 연속 자동순찰 중"
            if ISAAC_AUTO_PATROL_DEFAULT
            else "Isaac 자동순찰 대기"
        ),
    }
    qr_scan_hold = {"until": 0.0}
    controller_ref = {"value": None}

    def on_drive_cmd(mode, speed, turn):
        manual_override["active"] = (mode == "manual")
        if mode == "auto":
            auto_patrol["emergency_latched"] = False
            auto_patrol["operator_hold"] = False
            auto_patrol["enabled"] = True
            auto_patrol["requested_laps"] = 0
            auto_patrol["target_completed_laps"] = None
            auto_patrol["next_run_at"] = None
            auto_patrol["mode"] = "patrol"
            auto_patrol["phase"] = "driving"
            auto_patrol["message"] = "Isaac 전체 연구실 연속 자동순찰 중"
        elif mode == "manual" and (abs(speed) > 0.01 or abs(turn) > 0.01):
            # 강제정지 뒤 사용자가 새 주행 명령을 명확히 넣으면 래치를 해제한다.
            # 자동순찰 자체는 다시 켜지지 않아 손을 놓은 뒤 예기치 않게 출발하지 않는다.
            auto_patrol["emergency_latched"] = False
            auto_patrol["operator_hold"] = False
        manual_override["speed"] = speed
        manual_override["turn"] = turn
        manual_override["last_at"] = time.time()
        return {"mode": mode, "speed": speed, "turn": turn}

    def on_servo_cmd(pan, tilt):
        return hal.set_servo_angle(pan=pan, tilt=tilt)

    def on_scan_req():
        # 사용자가 물품을 로봇 카메라에 보여주는 동안 주행을 잠시 멈춘다.
        qr_scan_hold["until"] = time.time() + 2.0
        hal.stop()
        controller_now = controller_ref["value"]
        guide = controller_now.guide_status() if controller_now else {"status": "idle"}
        if guide.get("scene_object_id"):
            # Isaac에서는 DB의 QR 비밀값을 장면에 넣지 않는다. 사용자가 스캔 버튼을
            # 눌렀을 때 현재 안내 물품의 바인딩 키를 가상 QR 결과로 반환한다.
            return {
                "code": guide["scene_object_id"],
                "code_type": "scene_object_id",
                "item_name": guide.get("item_name", ""),
            }
        location = hal.try_read_qr()
        if location:
            items_here = [it for it in items if it.get("location") == location]
            names = ", ".join(it["name"] for it in items_here) if items_here else "(등록된 물품 없음)"
            print(f"[LabBot] Manual scan: {location} - {names}")
            report_event_async("INFO", severity="LOW", note=f"온디맨드 QR 스캔: {location}", source="isaac-sim")
            return {"code": location, "code_type": "zone"}
        return None

    def on_guide_start(params):
        controller_now = controller_ref["value"]
        if controller_now is None:
            raise RuntimeError("안내 제어기가 아직 준비되지 않았습니다.")
        mode = params.get("mission_type") or params.get("mode", "pickup")
        try:
            requested_item_id = int(params.get("item_id", 0))
        except (TypeError, ValueError):
            requested_item_id = 0
        requested_item = next((item for item in items if int(item.get("id", 0)) == requested_item_id), {})
        target = resolve_guide_target(
            item_name=requested_item.get("name", ""),
            mode=mode,
            location=requested_item.get("location", ""),
            category=requested_item.get("item_type") or requested_item.get("category", ""),
        )
        if target is None:
            raise ValueError("이 물품의 로봇 안내 좌표가 아직 등록되지 않았습니다.")
        item_binding = resolve_guide_target(
            item_name=requested_item.get("name", ""),
            mode="pickup",
        )
        pos_x, pos_y, _, _ = hal._position_and_heading()
        route = [tuple(point) for point in target["route"]]
        nearest_index = min(range(len(route)), key=lambda idx: math.hypot(route[idx][0] - pos_x, route[idx][1] - pos_y))
        item_id_text = str(params.get("item_id", "0"))
        try:
            item_id = max(1, int(item_id_text))
        except (TypeError, ValueError):
            item_id = 1
        shelf_row = target.get("shelf_row") or ((item_id - 1) // 4) % 3 + 1
        shelf_slot = target.get("shelf_slot") or ((item_id - 1) % 4) + 1
        location_detail = target.get("location_detail") if target.get("shelf_row") else None
        if not location_detail:
            side = "왼쪽" if str(target.get("shelf_code", "A")).startswith("A") else "오른쪽"
            location_detail = f"{target.get('shelf_code', '물품')} 선반 {shelf_row}번째 줄, {side}에서 {shelf_slot}번째 칸(번호표 {item_id})"
        task = {
            "task_id": params.get("request_id") or params.get("loan_id") or f"guide-{int(time.time())}",
            "mode": mode,
            "item_name": requested_item.get("name", target.get("item_query", "물품")),
            "scene_object_id": target.get("scene_object_id") or (item_binding or {}).get("scene_object_id", ""),
            "zone_type": target.get("zone_type", "lab_inventory"),
            "access_level": target.get("access_level", "authorized"),
            "shelf_code": target.get("shelf_code", "LAB-ST"),
            "shelf_row": shelf_row,
            "shelf_slot": shelf_slot,
            "location_detail": location_detail,
            "target_x": target["target"][0],
            "target_y": target["target"][1],
            "waypoints": route[nearest_index:],
        }
        auto_patrol["emergency_latched"] = False
        auto_patrol["operator_hold"] = False
        manual_override["active"] = False
        result = controller_now.start_guide(task)
        run_log.write("guide_started", **{k: v for k, v in result.items() if k != "waypoints"})
        print(f"[LabBot] Guide started: {task['item_name']} -> {task['shelf_code']}")
        return result

    def on_guide_status():
        controller_now = controller_ref["value"]
        return controller_now.guide_status() if controller_now else {"status": "initializing"}

    def on_guide_finish(status):
        controller_now = controller_ref["value"]
        if controller_now is None:
            return {"status": "idle"}
        result = controller_now.finish_guide(status)
        run_log.write("guide_finished", **result)
        return result

    def provide_patrol_status():
        controller_now = controller_ref["value"]
        pos_x, pos_y, forward_x, forward_y = hal._position_and_heading()
        if controller_now is None:
            return {
                "running": False,
                "phase": "starting",
                "x_cm": round(pos_x * 100.0, 1),
                "y_cm": round(pos_y * 100.0, 1),
                "heading_deg": round(math.degrees(math.atan2(forward_y, forward_x)), 1),
                "message": "Isaac 순찰 제어기 초기화 중",
            }

        raw = controller_now.patrol_status()
        completed_since_start = max(
            0,
            controller_now.completed_laps - auto_patrol["start_completed_laps"],
        )
        dock_active = bool(controller_now.guide_task and controller_now.guide_task.get("mode") == "dock")
        running = bool(auto_patrol["enabled"] or dock_active)
        if auto_patrol["emergency_latched"]:
            running = False
            phase = "emergency_stop"
            message = "강제정지 유지 중 · 새 주행/순찰/복귀 명령 전까지 움직이지 않습니다."
        elif dock_active:
            phase = "returning"
            message = "안전한 웨이포인트 경로로 대기 위치에 복귀 중입니다."
        elif controller_now.guide_task:
            phase = "paused_for_guide"
            message = "물품 안내가 끝나면 현재 경로에서 자동순찰을 이어갑니다."
        elif controller_now.avoidance_status().get("active"):
            phase = "blocked"
            message = "장애물을 확인해 우회한 뒤 순찰 경로에 복귀합니다."
        elif running:
            phase = "driving"
            message = auto_patrol["message"]
        else:
            phase = auto_patrol["phase"]
            message = auto_patrol["message"]

        requested_laps = auto_patrol["requested_laps"]
        current_lap = completed_since_start + 1 if running else completed_since_start
        if requested_laps > 0:
            current_lap = min(max(1, current_lap), requested_laps)
        return {
            "running": running,
            "phase": phase,
            "map": "Isaac 전체 연구실 자동순찰",
            "env": "isaac",
            "lap": current_lap,
            "laps": requested_laps,
            "leg": raw["waypoint_index"],
            "legs": max(1, raw["waypoint_count"] - 1),
            "completed_laps": controller_now.completed_laps,
            "repeat_minutes": auto_patrol["repeat_minutes"],
            "next_run_at": auto_patrol["next_run_at"],
            "emergency_latched": auto_patrol["emergency_latched"],
            "operator_hold": auto_patrol["operator_hold"],
            "control_mode": auto_patrol["mode"],
            "target_x_cm": round(raw["target_x"] * 100.0, 1),
            "target_y_cm": round(raw["target_y"] * 100.0, 1),
            "x_cm": round(pos_x * 100.0, 1),
            "y_cm": round(pos_y * 100.0, 1),
            "heading_deg": round(math.degrees(math.atan2(forward_y, forward_x)), 1),
            "message": message,
        }

    def start_patrol_cycle(laps=1, message=None, mode="patrol"):
        controller_now = controller_ref["value"]
        if controller_now is None:
            raise RuntimeError("Isaac 순찰 제어기가 아직 준비되지 않았습니다.")
        laps = max(0, min(int(laps), 99))
        auto_patrol["emergency_latched"] = False
        auto_patrol["operator_hold"] = False
        auto_patrol["enabled"] = True
        auto_patrol["requested_laps"] = laps
        auto_patrol["start_completed_laps"] = controller_now.completed_laps
        auto_patrol["target_completed_laps"] = (
            controller_now.completed_laps + laps if laps > 0 else None
        )
        auto_patrol["next_run_at"] = None
        auto_patrol["mode"] = mode
        auto_patrol["phase"] = "driving"
        auto_patrol["message"] = message or (
            f"Isaac 전체 연구실 {laps}바퀴 자동순찰 중"
            if laps
            else "Isaac 전체 연구실 연속 자동순찰 중"
        )
        manual_override["active"] = False

    def dock_route(controller_now):
        """현재 순찰선에서 앞/뒤 중 짧은 안전 경로를 골라 원점으로 복귀한다."""
        current_x, current_y, _, _ = hal._position_and_heading()
        points = [tuple(point) for point in controller_now.track_points]
        index = controller_now.target_index
        home = points[0]
        forward = points[index:]
        backward = list(reversed(points[:index]))

        def normalized(route):
            result = list(route)
            if not result or result[-1] != home:
                result.append(home)
            compact = []
            for point in result:
                if not compact or point != compact[-1]:
                    compact.append(point)
            return compact

        def route_length(route):
            total = 0.0
            previous = (current_x, current_y)
            for point in route:
                total += math.hypot(point[0] - previous[0], point[1] - previous[1])
                previous = point
            return total

        candidates = [normalized(forward), normalized(backward)]
        return min(candidates, key=route_length)

    def on_patrol(action, params):
        """실물 순찰과 섞이지 않는 Isaac 전용 좌표 순찰 HTTP API."""
        requested_env = (params.get("env") or "isaac").lower()
        if requested_env not in ("isaac", "sim"):
            raise ValueError("이 서버는 Isaac Sim 순찰 경로만 실행합니다.")
        controller_now = controller_ref["value"]

        if action == "map":
            return _isaac_patrol_map()
        if action == "status":
            return provide_patrol_status()
        if action == "pose":
            status = provide_patrol_status()
            return {
                "x_cm": status["x_cm"],
                "y_cm": status["y_cm"],
                "heading_deg": status["heading_deg"],
            }
        if controller_now is None:
            raise RuntimeError("Isaac 순찰 제어기가 아직 준비되지 않았습니다.")

        if action == "start":
            if controller_now.guide_task:
                return {"error": "물품 안내 중입니다. 안내 완료 후 순찰을 시작해주세요."}
            try:
                laps = int(params.get("laps", 1))
            except (TypeError, ValueError):
                laps = 1
            start_patrol_cycle(laps=laps)
            run_log.write(
                "patrol_started",
                mode="route",
                laps=laps,
                waypoint_count=len(LAB_TRACK_POINTS_M),
            )
            return {
                "status": "started",
                "map": "Isaac 전체 연구실 자동순찰",
                "env": "isaac",
                "laps": laps,
                "waypoints": [item["name"] for item in _isaac_patrol_map()["waypoints"]],
            }
        if action == "dock":
            if controller_now.guide_task and controller_now.guide_task.get("mode") != "dock":
                return {"error": "물품 안내 중입니다. 안내 완료 후 복귀해주세요."}
            route = dock_route(controller_now)
            auto_patrol["repeat_minutes"] = 0
            auto_patrol["next_run_at"] = None
            auto_patrol["enabled"] = False
            auto_patrol["emergency_latched"] = False
            auto_patrol["operator_hold"] = False
            auto_patrol["mode"] = "dock"
            auto_patrol["phase"] = "returning"
            auto_patrol["message"] = "안전한 웨이포인트 경로로 대기 위치에 복귀 중"
            manual_override["active"] = False
            result = controller_now.start_guide({
                "task_id": f"dock-{int(time.time())}",
                "mode": "dock",
                "item_name": "대기 위치",
                "shelf_code": "HOME",
                "location_detail": "Isaac 대기 위치 (0, 0)",
                "target_x": 0.0,
                "target_y": 0.0,
                "arrival_tolerance": 0.10,
                "waypoints": route,
            })
            run_log.write("dock_started", waypoint_count=len(route))
            return {
                "status": "returning",
                "env": "isaac",
                "target": [0.0, 0.0],
                "waypoint_count": len(route),
                "route": route,
                "guide": result,
            }
        if action == "stop":
            if controller_now.guide_task and controller_now.guide_task.get("mode") == "dock":
                controller_now.finish_guide("aborted")
            auto_patrol["enabled"] = False
            auto_patrol["target_completed_laps"] = None
            auto_patrol["repeat_minutes"] = 0
            auto_patrol["next_run_at"] = None
            auto_patrol["operator_hold"] = True
            auto_patrol["mode"] = "stopped"
            auto_patrol["phase"] = "aborted"
            auto_patrol["message"] = "사용자가 Isaac 자동순찰을 중지했습니다."
            if not controller_now.guide_task:
                hal.stop()
            run_log.write("patrol_stopped", reason="user")
            return {"status": "stopped", "env": "isaac"}
        if action == "emergency_stop":
            if controller_now.guide_task:
                controller_now.finish_guide("aborted")
            auto_patrol["enabled"] = False
            auto_patrol["target_completed_laps"] = None
            auto_patrol["repeat_minutes"] = 0
            auto_patrol["next_run_at"] = None
            auto_patrol["emergency_latched"] = True
            auto_patrol["operator_hold"] = True
            auto_patrol["mode"] = "emergency_stop"
            auto_patrol["phase"] = "emergency_stop"
            auto_patrol["message"] = "강제정지 유지 중 · 새 명령 전까지 이동 금지"
            manual_override.update(active=False, speed=0.0, turn=0.0, last_at=time.time())
            hal.stop()
            run_log.write("emergency_stop", source="web")
            return {"status": "emergency_stopped", "latched": True, "env": "isaac"}
        if action == "repeat":
            try:
                minutes = int(params.get("minutes", 0))
            except (TypeError, ValueError):
                raise ValueError("자동반복 간격은 분 단위 숫자여야 합니다.")
            if minutes < -1 or minutes > 1440:
                raise ValueError("자동반복 간격은 연속(-1), 끔(0), 1~1440분만 가능합니다.")

            auto_patrol["emergency_latched"] = False
            if minutes == -1:
                auto_patrol["repeat_minutes"] = 0
                start_patrol_cycle(laps=0, message="Isaac 전체 연구실 연속 자동순찰 중")
                return {"status": "continuous", "repeat_minutes": 0, "next_run_at": None}

            auto_patrol["repeat_minutes"] = minutes
            auto_patrol["next_run_at"] = None
            if auto_patrol["enabled"] and auto_patrol["target_completed_laps"] is None:
                # 연속순찰 중 설정을 바꾸면 현재 바퀴까지만 마치고 새 정책으로 전환한다.
                auto_patrol["requested_laps"] = 1
                auto_patrol["start_completed_laps"] = controller_now.completed_laps
                auto_patrol["target_completed_laps"] = controller_now.completed_laps + 1
                auto_patrol["message"] = (
                    f"현재 바퀴 완료 후 {minutes}분 간격 자동반복"
                    if minutes
                    else "현재 바퀴 완료 후 대기"
                )
            elif not auto_patrol["enabled"] and minutes > 0:
                auto_patrol["operator_hold"] = True
                auto_patrol["phase"] = "idle"
                auto_patrol["next_run_at"] = time.time() + minutes * 60.0
                auto_patrol["message"] = f"{minutes}분 후 Isaac 자동순찰 예정"
            return {
                "status": "scheduled" if minutes else "repeat_off",
                "repeat_minutes": minutes,
                "next_run_at": auto_patrol["next_run_at"],
            }

        raise ValueError(f"지원하지 않는 Isaac 순찰 명령: {action}")

    def provide_telemetry():
        dist = hal.read_ultrasonic()
        obstacle_context = hal.obstacle_context()
        pos_x, pos_y, forward_x, forward_y = hal._position_and_heading()
        nearest_zone = min(
            LAB_ZONES,
            key=lambda zone: math.hypot(
                pos_x - zone["checkpoint"]["x"], pos_y - zone["checkpoint"]["y"]
            ),
        )
        nearest_distance = math.hypot(
            pos_x - nearest_zone["checkpoint"]["x"],
            pos_y - nearest_zone["checkpoint"]["y"],
        )
        zone_name = nearest_zone["name"] if nearest_distance <= 1.8 else "보안 실험구역 복도"
        is_manual = manual_override["active"] and (time.time() - manual_override["last_at"] < MANUAL_COMMAND_MAX_AGE_SECONDS)
        distance_cm = dist if dist < 900 else 999.0
        controller_now = controller_ref["value"]
        return {
            "mode": "manual" if is_manual else "auto",
            "speed": hal.last_speed,
            "turn": hal.last_turn,
            "distance_cm": distance_cm,
            "obstacle_cm": distance_cm,
            "obstacle_kind": obstacle_context["kind"],
            "obstacle_prim": obstacle_context["path"],
            "zone": zone_name,
            "cam_pan": hal.cam_pan,
            "cam_tilt": hal.cam_tilt,
            "x": round(pos_x, 4),
            "y": round(pos_y, 4),
            "heading_deg": round(math.degrees(math.atan2(forward_y, forward_x)), 2),
            "streaming": True,
            "operation": (
                "emergency_stop" if auto_patrol["emergency_latched"]
                else "dock" if controller_now and controller_now.guide_task and controller_now.guide_task.get("mode") == "dock"
                else "guide" if controller_now and controller_now.guide_task
                else "patrol" if auto_patrol["enabled"] and not is_manual
                else "patrol_wait" if auto_patrol["repeat_minutes"] > 0 and auto_patrol["next_run_at"]
                else "docked" if auto_patrol["mode"] == "docked"
                else "stopped" if auto_patrol["operator_hold"]
                else "night_guard" if night_guard.status().get("active")
                else "rental_assist"
            ),
            "guide": controller_now.guide_status() if controller_now else {"status": "initializing"},
            "patrol": provide_patrol_status(),
            "avoidance": controller_now.avoidance_status() if controller_now else {"active": False, "state": "idle", "label": "초기화 중"},
            "night_guard": night_guard.status(),
        }

    stream_server.set_drive_callback(on_drive_cmd)
    stream_server.set_camera_angle_callback(on_servo_cmd)
    stream_server.set_qr_scan_callback(on_scan_req)
    stream_server.set_telemetry_provider(provide_telemetry)
    stream_server.set_guide_callbacks(start=on_guide_start, status=on_guide_status, finish=on_guide_finish)
    stream_server.set_guard_callbacks(
        status=night_guard.status,
        configure=night_guard.configure,
        trigger=night_guard.trigger,
    )

    # 5. 자율 순찰 컨트롤러 초기화
    last_obstacle_alert_time = 0.0

    def on_scan(location):
        items_here = [it for it in items if it.get("location") == location]
        names = ", ".join(it["name"] for it in items_here) if items_here else "(등록된 물품 없음)"
        print(f"[LabBot] Checkpoint scanned: {location} - {names}")
        run_log.write("checkpoint_scanned", checkpoint=location)

    def on_obstacle(distance):
        nonlocal last_obstacle_alert_time
        obstacle_context = hal.obstacle_context()
        obstacle_kind = obstacle_context["kind"]
        if obstacle_kind.startswith("static_"):
            # 벽/파티션/고정 가구는 정상적인 환경 구조다. 로봇은 정지·재탐색하되
            # 안전사고 DB에는 적치물 사건으로 올리지 않는다.
            print(
                f"[LabBot] Static structure ahead ({distance:.1f}cm, "
                f"{obstacle_context['path']}) - route correction"
            )
            run_log.write(
                "static_obstacle_avoided",
                distance_cm=round(distance, 2),
                kind=obstacle_kind,
                prim_path=obstacle_context["path"],
            )
            return
        now = time.time()
        if now - last_obstacle_alert_time >= OBSTACLE_ALERT_COOLDOWN:
            last_obstacle_alert_time = now
            pos_x, pos_y, _, _ = hal._position_and_heading()
            print(f"[LabBot] Obstacle detected ({distance:.1f}cm) - Stop + SR-01 alert sent")
            run_log.write(
                "obstacle_detected",
                distance_cm=round(distance, 2),
                rule_id="SR-01",
                x_m=round(pos_x, 2),
                y_m=round(pos_y, 2),
            )
            report_event_async(
                "SR-01",
                severity="MEDIUM",
                note=(
                    f"Isaac Sim 순찰 중 장애물 감지 ({distance:.1f}cm) · "
                    f"좌표 ({pos_x:.2f}, {pos_y:.2f})m"
                ),
                source="isaac-sim",
            )

    def on_obstacle_cleared():
        controller_now = controller_ref["value"]
        result = controller_now.avoidance_status().get("last_result", "cleared") if controller_now else "cleared"
        print(f"[LabBot] Obstacle handled ({result}) - Rejoining route")
        run_log.write("obstacle_cleared", result=result)

    def on_guide_arrived(task):
        if task.get("mode") == "dock":
            controller_now = controller_ref["value"]
            if controller_now is not None:
                controller_now.finish_guide("completed")
            dock_x, dock_y, _, _ = hal._position_and_heading()
            auto_patrol["enabled"] = False
            auto_patrol["operator_hold"] = True
            auto_patrol["mode"] = "docked"
            auto_patrol["phase"] = "done"
            auto_patrol["message"] = "Isaac 로봇이 대기 위치에 복귀했습니다."
            run_log.write("dock_completed", x_m=round(dock_x, 3), y_m=round(dock_y, 3))
            print(f"[LabBot] Dock arrived: HOME ({dock_x:.2f}, {dock_y:.2f})")
            return
        print(f"[LabBot] Guide arrived: {task.get('item_name')} / {task.get('shelf_code')}")
        run_log.write("guide_arrived", item_name=task.get("item_name"), shelf_code=task.get("shelf_code"))

    controller = WaypointPatrolController(
        hal,
        LAB_TRACK_POINTS_M,
        on_scan=on_scan,
        on_obstacle=on_obstacle,
        on_obstacle_cleared=on_obstacle_cleared,
        on_guide_arrived=on_guide_arrived,
    )
    controller_ref["value"] = controller
    stream_server.set_patrol_callback(on_patrol)
    last_guard_transition_id = night_guard.status()["transition_id"]

    tick = 0
    print(
        f"[LabBot] Isaac Sim Biotech Lab Patrol Started! "
        f"auto={auto_patrol['enabled']} waypoints={len(LAB_TRACK_POINTS_M)}"
    )
    try:
        while simulation_app.is_running():
            tick += 1

            # 0. 메인 스레드에서 PhysX 상태 동기화 (멀티스레드 충돌 방지)
            hal.update_tick_cache()

            # 1. 수동 조작 vs 자동 순찰 제어
            now = time.time()
            guard = night_guard.update(sonar_cm=hal.read_ultrasonic())
            next_run_at = auto_patrol["next_run_at"]
            if (
                not auto_patrol["emergency_latched"]
                and not auto_patrol["enabled"]
                and auto_patrol["repeat_minutes"] > 0
                and next_run_at is not None
                and now >= next_run_at
                and not controller.guide_task
            ):
                start_patrol_cycle(
                    laps=1,
                    message=f"{auto_patrol['repeat_minutes']}분 간격 Isaac 자동순찰 중",
                    mode="scheduled_patrol",
                )
                run_log.write(
                    "patrol_repeat_started",
                    interval_minutes=auto_patrol["repeat_minutes"],
                )
            if guard["transition_id"] != last_guard_transition_id:
                last_guard_transition_id = guard["transition_id"]
                print(f"[LabBot] Night guard: {guard['label']} {guard.get('reason', '')}".rstrip())
                run_log.write(
                    "night_guard_transition",
                    state=guard["state"],
                    reason=guard.get("reason", ""),
                )
                if guard["state"] == "investigating":
                    event_x, event_y, _, _ = hal._position_and_heading()
                    report_event_async(
                        "NIGHT-GUARD",
                        severity="HIGH" if "사람" in guard.get("reason", "") else "MEDIUM",
                        note=(
                            f"Isaac Sim 야간 경비 출동: {guard.get('reason', '이상 신호')} · "
                            f"좌표 ({event_x:.2f}, {event_y:.2f})m"
                        ),
                        source="isaac-sim",
                    )
            if auto_patrol["emergency_latched"]:
                hal.stop()
            elif now < qr_scan_hold["until"]:
                hal.stop()
            elif manual_override["active"]:
                if now - manual_override["last_at"] >= MANUAL_COMMAND_MAX_AGE_SECONDS:
                    # 데드맨 타임아웃 뒤에는 정지만 하지 말고 자동 순찰권도 반환한다.
                    manual_override["active"] = False
                    hal.stop()
                else:
                    distance = hal.read_ultrasonic()
                    # 전방 이동 시에만 장애물 감지하여 정지 (후진 또는 제자리 회전은 허용)
                    if distance < OBSTACLE_STOP_DISTANCE and manual_override["speed"] > 0:
                        hal.stop()
                    else:
                        hal.set_motion(manual_override["speed"], manual_override["turn"])
            else:
                # 물품 안내는 밤에도 최우선. 그 외에는 Isaac 자동순찰 또는 야간
                # 조사 중에만 움직이고, 자동순찰을 끈 대기 상태에서는 모터를 정지한다.
                guard_should_move = guard["should_move"] and not auto_patrol["operator_hold"]
                if controller.guide_task or guard_should_move or auto_patrol["enabled"]:
                    controller.tick(TIME_STEP_S)
                    target_laps = auto_patrol["target_completed_laps"]
                    if (
                        auto_patrol["enabled"]
                        and target_laps is not None
                        and controller.completed_laps >= target_laps
                        and not controller.guide_task
                    ):
                        auto_patrol["enabled"] = False
                        auto_patrol["target_completed_laps"] = None
                        auto_patrol["operator_hold"] = True
                        repeat_minutes = auto_patrol["repeat_minutes"]
                        if repeat_minutes > 0:
                            auto_patrol["next_run_at"] = now + repeat_minutes * 60.0
                            auto_patrol["phase"] = "idle"
                            auto_patrol["message"] = f"순찰 완료 · {repeat_minutes}분 후 다음 자동순찰"
                        else:
                            auto_patrol["phase"] = "done"
                            auto_patrol["message"] = "Isaac 전체 연구실 순찰을 완료하고 대기 위치에 복귀했습니다."
                        hal.stop()
                        run_log.write(
                            "patrol_completed",
                            laps=auto_patrol["requested_laps"],
                            completed_laps=controller.completed_laps,
                        )
                else:
                    hal.stop()

            # 2. 로봇 위치 및 Pan/Tilt 각도를 합성하여 FPV 카메라 회전 동기화
            rx, ry, fx, fy = hal._position_and_heading()
            heading = math.atan2(fy, fx)
            camera_forward = float(camera_spec["forwardOffsetM"])
            camera_height = float(camera_spec["heightM"])
            eye_pos = np.array([rx + fx * camera_forward, ry + fy * camera_forward, camera_height])
            cam_q = _compute_camera_quaternion(eye_pos, heading, hal.cam_pan, hal.cam_tilt)
            cam.set_world_pose(
                position=eye_pos,
                orientation=cam_q,
                camera_axes="usd",
            )

            world.step(render=True)

            # 3. 렌더 틱마다 FPV를 전송해 고화질 설정에서도 조작 반응성을 유지한다.
            if tick % STREAM_EVERY_N_TICKS == 0:
                frame = hal.capture_fpv_frame()
                _, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                stream_server.set_camera_frame(jpeg.tobytes())

            # 2 FPS면 프리뷰로는 충분하고, FPV 30 FPS와 분리해 RTX 5070 렌더 부하를
            # 억제한다. 정적 캡처를 확대하는 대신 현재 USD 장면을 직접 렌더링한다.
            if tick % LAB_PREVIEW_EVERY_N_TICKS == 0:
                overview_rgb = overview_cam.get_rgb()
                if overview_rgb is not None and getattr(overview_rgb, "size", 0) > 0:
                    if np.issubdtype(overview_rgb.dtype, np.floating):
                        overview_rgb = np.clip(overview_rgb * 255.0, 0, 255).astype(np.uint8)
                    else:
                        overview_rgb = np.ascontiguousarray(overview_rgb, dtype=np.uint8)
                    overview_bgr = cv2.cvtColor(overview_rgb[:, :, :3], cv2.COLOR_RGB2BGR)
                    _, preview_jpeg = cv2.imencode(
                        ".jpg",
                        overview_bgr,
                        [int(cv2.IMWRITE_JPEG_QUALITY), max(86, JPEG_QUALITY)],
                    )
                    stream_server.set_lab_preview_frame(preview_jpeg.tobytes())

            if tick % TELEMETRY_LOG_EVERY == 0:
                run_log.write(
                    "telemetry",
                    sim_time_s=round(tick * TIME_STEP_S, 3),
                    mode="manual" if manual_override["active"] else "auto",
                    command_speed=hal.last_speed,
                    command_turn=hal.last_turn,
                    obstacle_cm=round(hal.read_ultrasonic(), 2),
                    obstacle_kind=hal.classify_obstacle(),
                    night_guard_state=guard["state"],
                )
    except KeyboardInterrupt:
        print("[LabBot] Ctrl+C — 종료합니다")
    except Exception as e:
        import traceback
        print("[LabBot] Main loop exception:")
        traceback.print_exc()
    finally:
        network_executor.shutdown(wait=False, cancel_futures=True)
        run_log.close()
        simulation_app.close()


if __name__ == "__main__":
    main()
