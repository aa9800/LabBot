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
OBSTACLE_STOP_DISTANCE = 40.0
MANUAL_COMMAND_MAX_AGE_SECONDS = 3.0  # 실물(run_real.py)과 동일하게 맞춤 — 1초면 키보드 주행이 끊긴다
FPV_WIDTH = int(os.environ.get("LABKEEPER_FPV_WIDTH", "960"))
FPV_HEIGHT = int(os.environ.get("LABKEEPER_FPV_HEIGHT", "540"))
JPEG_QUALITY = max(65, min(95, int(os.environ.get("LABKEEPER_JPEG_QUALITY", "84"))))
STREAM_EVERY_N_TICKS = max(1, int(os.environ.get("LABKEEPER_STREAM_EVERY_N_TICKS", "1")))
LAB_PREVIEW_WIDTH = int(os.environ.get("LABKEEPER_PREVIEW_WIDTH", "1280"))
LAB_PREVIEW_HEIGHT = int(os.environ.get("LABKEEPER_PREVIEW_HEIGHT", "720"))
LAB_PREVIEW_EVERY_N_TICKS = max(15, int(os.environ.get("LABKEEPER_PREVIEW_EVERY_N_TICKS", "30")))


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
    qr_scan_hold = {"until": 0.0}
    controller_ref = {"value": None}

    def on_drive_cmd(mode, speed, turn):
        manual_override["active"] = (mode == "manual")
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
                "guide" if controller_now and controller_now.guide_task
                else "night_guard" if night_guard.status().get("active")
                else "rental_assist"
            ),
            "guide": controller_now.guide_status() if controller_now else {"status": "initializing"},
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
            print(f"[LabBot] Obstacle detected ({distance:.1f}cm) - Stop + SR-01 alert sent")
            run_log.write("obstacle_detected", distance_cm=round(distance, 2), rule_id="SR-01")
            report_event_async(
                "SR-01", severity="MEDIUM", note=f"Isaac Sim 순찰 중 장애물 감지 ({distance:.1f}cm)", source="isaac-sim"
            )

    def on_obstacle_cleared():
        controller_now = controller_ref["value"]
        result = controller_now.avoidance_status().get("last_result", "cleared") if controller_now else "cleared"
        print(f"[LabBot] Obstacle handled ({result}) - Rejoining route")
        run_log.write("obstacle_cleared", result=result)

    def on_guide_arrived(task):
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
    last_guard_transition_id = night_guard.status()["transition_id"]

    tick = 0
    print("[LabBot] Isaac Sim Biotech Lab Patrol Started!")
    try:
        while simulation_app.is_running():
            tick += 1

            # 0. 메인 스레드에서 PhysX 상태 동기화 (멀티스레드 충돌 방지)
            hal.update_tick_cache()

            # 1. 수동 조작 vs 자동 순찰 제어
            now = time.time()
            guard = night_guard.update(sonar_cm=hal.read_ultrasonic())
            if guard["transition_id"] != last_guard_transition_id:
                last_guard_transition_id = guard["transition_id"]
                print(f"[LabBot] Night guard: {guard['label']} {guard.get('reason', '')}".rstrip())
                run_log.write(
                    "night_guard_transition",
                    state=guard["state"],
                    reason=guard.get("reason", ""),
                )
                if guard["state"] == "investigating":
                    report_event_async(
                        "NIGHT-GUARD",
                        severity="HIGH" if "사람" in guard.get("reason", "") else "MEDIUM",
                        note=f"Isaac Sim 야간 경비 출동: {guard.get('reason', '이상 신호')}",
                        source="isaac-sim",
                    )
            if now < qr_scan_hold["until"]:
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
                # 물품 안내는 밤에도 최우선. 그 외에는 정기순찰/조사 중에만 움직이고
                # 대기 상태에서는 모터를 끈 채 센서만 유지한다.
                if controller.guide_task or guard["should_move"]:
                    controller.tick(TIME_STEP_S)
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
