"""Isaac Sim 진입점 — LabKeeper 9개 구역 풀스케일 가상 실험실 및 실시간 웹 연동 (Sim-to-Real).

1. 9대 보관 구역(기기실-1, 2, 세포배양실, 시약실 등) 디지털 트윈 구축
2. 30 FPS 실시간 FPV 스트리밍 서버(8080) 연동 -> admin.html에서 즉시 관제
3. 웹 [물품 QR 인식하기] 온디맨드 스캔 & Supabase 실사 기록 연동
4. 초음파/라인트래킹 안전 순찰 로직 검증
"""
import datetime
import math
import os
import sys
import threading
import time
import cv2
import numpy as np

os.environ.setdefault("LABKEEPER_ISAAC_HEADLESS", "0")
_HEADLESS = os.environ.get("LABKEEPER_ISAAC_HEADLESS", "0") == "1"

from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": _HEADLESS})

import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402
from isaacsim.storage.native import get_assets_root_path  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402

_ROBOT_SIM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROBOT_SIM_ROOT)
from controller import PatrolController, OBSTACLE_STOP_DISTANCE  # noqa: E402
from notify_supabase import (  # noqa: E402
    fetch_items,
    fetch_robot_command,
    is_configured,
    report_safety_event,
)
from run_logger import JsonlRunLogger  # noqa: E402
import stream_server  # noqa: E402

from lab_world import LAB_TRACK_POINTS_M, LAB_ZONES, build_lab_environment, get_all_checkpoints  # noqa: E402
from isaac_hal import IsaacHAL  # noqa: E402

OBSTACLE_PATH = "/World/Obstacle"
OBSTACLE_PARKED_XY = (100.0, 100.0)

TIME_STEP_S = 1.0 / 60.0
COMMAND_POLL_EVERY = 30
TELEMETRY_LOG_EVERY = 60
MANUAL_COMMAND_MAX_AGE_SECONDS = 3.0
OBSTACLE_ALERT_COOLDOWN = 15.0


def _command_age_seconds(command):
    updated_at = command.get("updated_at")
    if not updated_at:
        return float("inf")
    try:
        ts = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - ts).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def _create_obstacle(stage):
    prim = stage.DefinePrim(OBSTACLE_PATH, "Cube")
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    translate_op = xform.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(OBSTACLE_PARKED_XY[0], OBSTACLE_PARKED_XY[1], 0.05))
    xform.AddScaleOp().Set(Gf.Vec3d(0.08, 0.08, 0.08))
    return translate_op


def main():
    log_dir = os.path.join(_ROBOT_SIM_ROOT, "logs")
    run_log = JsonlRunLogger(log_dir, source="isaac")
    print(f"[LabKeeper] 🚀 Isaac Sim 주행 로그: {run_log.path}")

    items = fetch_items()
    checkpoints = get_all_checkpoints()
    print(f"[LabKeeper] 9대 연구실 보관 구역 체크포인트 로드 완료: {[c['name'] for c in checkpoints]}")

    assets_root = get_assets_root_path()
    jetbot_usd = assets_root + "/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd"

    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()

    # 1. 9개 구역 디지털 트윈 및 라인트랙 구축
    stage = omni.usd.get_context().get_stage()
    build_lab_environment(stage)
    _create_obstacle(stage)

    # 2. 로봇 에셋 로드 및 시작 위치 배치
    add_reference_to_stage(usd_path=jetbot_usd, prim_path="/World/Jetbot")
    jetbot = Articulation(prim_paths_expr="/World/Jetbot", name="jetbot")
    world.scene.add(jetbot)
    world.reset()

    start_x, start_y = LAB_TRACK_POINTS_M[0]
    next_x, next_y = LAB_TRACK_POINTS_M[1]
    heading = math.atan2(next_y - start_y, next_x - start_x)
    qz, qw = math.sin(heading / 2), math.cos(heading / 2)
    jetbot.set_world_poses(
        positions=np.array([[start_x, start_y, 0.0]]),
        orientations=np.array([[qw, 0.0, 0.0, qz]]),
    )

    hal = IsaacHAL(stage, jetbot, obstacle_prim_path=OBSTACLE_PATH, checkpoints=checkpoints)

    # 3. 로컬 30 FPS 웹 스트림 서버 시작 (admin.html 연동)
    try:
        stream_server.start_stream_server(port=8080)
        print("[LabKeeper] 🟢 실시간 웹 FPV 스트림 서버 가동 (http://localhost:8080/stream)")
    except Exception as e:
        print(f"[LabKeeper] ⚠️ 스트림 서버 기동 알림: {e}")

    # 스트림 서버 콜백 연결 (수동 운전 / 서보 / 온디맨드 QR 스캔)
    manual_override = {"active": False, "speed": 0.0, "turn": 0.0, "last_at": 0.0}

    def on_drive_cmd(mode, speed, turn):
        manual_override["active"] = (mode == "manual")
        manual_override["speed"] = speed
        manual_override["turn"] = turn
        manual_override["last_at"] = time.time()

    def on_cam_cmd(pan, tilt):
        hal.set_servo_angle(pan=pan, tilt=tilt)

    def on_manual_qr_scan():
        qr_result = hal.scan_qr_now()
        if qr_result:
            print(f"[LabKeeper] 🔍 [온디맨드 물품 QR 인식]: {qr_result}")
            run_log.write("manual_qr_scan_success", qr=qr_result)
            return {"success": True, "data": qr_result}
        return {"success": False, "message": "근처에 인식 가능한 물품 QR이 없습니다."}

    def telemetry_provider():
        x, y, _, _ = hal._position_and_heading()
        return {
            "distance_cm": round(hal.read_ultrasonic(), 1),
            "cam_pan": hal.cam_pan,
            "cam_tilt": hal.cam_tilt,
            "speed": hal.last_speed,
            "turn": hal.last_turn,
            "mode": "manual" if manual_override["active"] else "auto",
            "pos_x": round(x, 2),
            "pos_y": round(y, 2),
        }

    stream_server.set_drive_callback(on_drive_cmd)
    stream_server.set_camera_callback(on_cam_cmd)
    stream_server.set_scan_qr_callback(on_manual_qr_scan)
    stream_server.set_telemetry_provider(telemetry_provider)

    last_obstacle_alert_time = 0.0

    def on_scan(location):
        items_here = [it for it in items if it.get("location") == location]
        names = ", ".join(it["name"] for it in items_here) if items_here else "(등록된 물품 없음)"
        print(f"[LabKeeper] 📍 정기 순찰 체크포인트 확인: {location} — {names}")
        run_log.write("checkpoint_scanned", checkpoint=location)

    def on_obstacle(distance):
        nonlocal last_obstacle_alert_time
        now = time.time()
        if now - last_obstacle_alert_time >= OBSTACLE_ALERT_COOLDOWN:
            last_obstacle_alert_time = now
            print(f"[LabKeeper] 🛑 장애물 감지({distance:.1f}cm) — 정지 + SR-01 안전이벤트 전송")
            run_log.write("obstacle_detected", distance_cm=round(distance, 2), rule_id="SR-01")
            report_safety_event(
                "SR-01", severity="MEDIUM", note=f"Isaac Sim 순찰 중 장애물 감지 ({distance:.1f}cm)", source="isaac-sim"
            )

    def on_obstacle_cleared():
        print("[LabKeeper] 🟢 장애물 안전 해제 — 순찰 재개")
        run_log.write("obstacle_cleared")

    controller = PatrolController(
        hal, on_scan=on_scan, on_obstacle=on_obstacle, on_obstacle_cleared=on_obstacle_cleared
    )

    tick = 0
    print("[LabKeeper] 🏁 Isaac Sim 가상 실험실 순찰 시작!")
    try:
        while simulation_app.is_running():
            tick += 1

            # 1. 수동 조작 vs 자동 순찰 제어
            now = time.time()
            if manual_override["active"] and (now - manual_override["last_at"] < MANUAL_COMMAND_MAX_AGE_SECONDS):
                distance = hal.read_ultrasonic()
                if distance < OBSTACLE_STOP_DISTANCE:
                    hal.stop()
                else:
                    hal.set_motion(manual_override["speed"], manual_override["turn"])
            else:
                controller.tick(TIME_STEP_S)

            world.step(render=not _HEADLESS)

            # 2. 30 FPS 가상 FPV 카메라 프레임 생성 & 웹 스트림 전송
            if tick % 2 == 0:  # 60Hz 시뮬레이션 중 매 2스텝(30Hz)마다 프레임 갱신
                frame = hal.capture_fpv_frame()
                _, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                stream_server.set_camera_frame(jpeg.tobytes())

            if tick % TELEMETRY_LOG_EVERY == 0:
                run_log.write(
                    "telemetry",
                    sim_time_s=round(tick * TIME_STEP_S, 3),
                    mode="manual" if manual_override["active"] else "auto",
                    command_speed=hal.last_speed,
                    command_turn=hal.last_turn,
                    obstacle_cm=round(hal.read_ultrasonic(), 2),
                )
    except KeyboardInterrupt:
        print("[LabKeeper] Ctrl+C — 종료합니다")
    finally:
        run_log.close()
        simulation_app.close()


if __name__ == "__main__":
    main()
