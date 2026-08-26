"""실제 Raspbot(라즈베리파이5)에서 실행하는 진입점.

main.py(pygame)·labkeeper_controller.py(Webots)와 같은 구조를 그대로 따른다 —
controller.py(PatrolController)와 notify_supabase.py는 손대지 않고 그대로 재사용,
HAL만 RealHAL로 바꿔 끼운다.

실행 위치: 이 파일과 controller.py, notify_supabase.py, real_hal.py, run_logger.py,
.env를 전부 로봇의 같은 폴더에 올려두고 로봇에서 직접 `python3 run_real.py`로 실행한다.
(로봇에는 아직 안 올렸음 — 로봇이 실제 홈 Wi-Fi에 붙어서 Supabase에 닿을 수 있게 된
다음에 올리는 게 맞다. 지금은 코드만 준비해두는 단계.)

조작(터미널에서 Ctrl+C로 종료 외에는 무인 자동 순찰):
  - 웹 Robot Console에서 수동조작으로 바꾸면 여기서도 Webots와 동일하게 반응한다
    (3초 안에 새 명령이 안 오면 dead-man switch로 자동 정지).
  - SPACE/C/R/M/F/N 같은 pygame 키 조작은 실물에는 해당 사항이 없다(화면이 없음).
"""
import datetime
import os
import time

from controller import PatrolController, OBSTACLE_STOP_DISTANCE
from notify_supabase import (
    fetch_items,
    fetch_robot_command,
    report_safety_event,
    upload_camera_snapshot_bytes,
)
from real_hal import RealHAL
from run_logger import JsonlRunLogger
import stream_server

TICK_SECONDS = 0.05  # 20Hz — 실물 초음파 측정(최대 0.03초 x 2)이 있어서 pygame 60Hz보다 낮춤
COMMAND_POLL_EVERY = 10   # 약 0.5초마다 원격조작 명령 확인
CAMERA_UPLOAD_EVERY = 60  # 약 3초마다 카메라 스냅샷 업로드
TELEMETRY_LOG_EVERY = 20  # 약 1초마다 텔레메트리 기록
MANUAL_COMMAND_MAX_AGE_SECONDS = 3.0  # Webots와 동일한 dead-man switch 기준

_ROBOT_SIM_ROOT = os.path.dirname(os.path.abspath(__file__))


def _command_age_seconds(command):
    """labkeeper_controller.py와 동일한 로직 — updated_at을 못 읽으면 무조건 "끊김"으로 처리."""
    updated_at = command.get("updated_at")
    if not updated_at:
        return float("inf")
    try:
        ts = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - ts).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def main():
    log_dir = os.path.join(_ROBOT_SIM_ROOT, "logs")
    run_log = JsonlRunLogger(log_dir, source="real")
    print(f"[labkeeper] 주행 로그: {run_log.path}")

    items = fetch_items()
    items_by_location = {}
    for it in items:
        items_by_location.setdefault(it.get("location"), []).append(it)
    if items:
        print(f"[labkeeper] 웹에서 물품 {len(items)}개 불러옴 (Supabase)")
    else:
        print("[labkeeper] 웹에서 물품을 못 가져왔습니다 — .env 확인 (스캔은 되지만 물품 매칭은 안 됨)")

    hal = RealHAL(enable_camera=True)
    stream_server.set_camera_angle_callback(hal.set_camera_angle)
    scanned_ids = set()
    last_pan = 90
    last_tilt = 90

    def on_scan(location):
        items_here = items_by_location.get(location, [])
        names = ", ".join(it["name"] for it in items_here) if items_here else "(등록된 물품 없음)"
        print(f"[labkeeper] 체크포인트 확인: {location} — {names}")
        run_log.write("checkpoint_scanned", checkpoint=location)
        for it in items_here:
            scanned_ids.add(it["id"])

    def on_obstacle(distance):
        print(f"[labkeeper] 장애물 감지({distance:.1f}cm) — 정지 + SR-01 안전이벤트 전송")
        run_log.write("obstacle_detected", distance_cm=round(distance, 2), rule_id="SR-01")
        report_safety_event(
            "SR-01", severity="HIGH", note="실물 Raspbot 순찰 중 초음파 장애물 감지", source="real-raspbot"
        )

    def on_obstacle_cleared():
        print("[labkeeper] 장애물 사라짐 — 순찰 재개")
        run_log.write("obstacle_cleared")

    patrol = PatrolController(
        hal, on_scan=on_scan, on_obstacle=on_obstacle, on_obstacle_cleared=on_obstacle_cleared
    )

    tick = 0
    command = {"mode": "auto", "speed": 0.0, "turn": 0.0, "cam_pan": 90, "cam_tilt": 90}
    was_manual = False

    try:
        while True:
            loop_start = time.time()
            tick += 1

            if tick % COMMAND_POLL_EVERY == 0:
                command = fetch_robot_command()
                is_manual = command.get("mode") == "manual"
                if is_manual != was_manual:
                    print(f"[labkeeper] 모드 전환: {'수동조작' if is_manual else '자동순찰'}")
                    run_log.write("mode_changed", mode="manual" if is_manual else "auto")
                was_manual = is_manual

                new_pan = command.get("cam_pan")
                new_tilt = command.get("cam_tilt")
                if new_pan is not None or new_tilt is not None:
                    if new_pan != last_pan or new_tilt != last_tilt:
                        hal.set_camera_angle(new_pan, new_tilt)
                        if new_pan is not None:
                            last_pan = new_pan
                        if new_tilt is not None:
                            last_tilt = new_tilt

            if command.get("mode") == "manual":
                distance = hal.read_ultrasonic()
                stale = _command_age_seconds(command) > MANUAL_COMMAND_MAX_AGE_SECONDS
                if stale:
                    hal.stop()  # dead-man switch
                elif distance < OBSTACLE_STOP_DISTANCE:
                    hal.stop()
                else:
                    hal.set_motion(command.get("speed", 0.0), command.get("turn", 0.0))
            else:
                patrol.tick(TICK_SECONDS)

            if tick % CAMERA_UPLOAD_EVERY == 0:
                jpeg_bytes = stream_server.get_latest_frame()
                if jpeg_bytes:
                    upload_camera_snapshot_bytes(jpeg_bytes)

            if tick % TELEMETRY_LOG_EVERY == 0:
                run_log.write(
                    "telemetry",
                    mode=command.get("mode", "auto"),
                    command_speed=hal.last_speed,
                    command_turn=hal.last_turn,
                )

            elapsed = time.time() - loop_start
            time.sleep(max(0.0, TICK_SECONDS - elapsed))
    except KeyboardInterrupt:
        print("[labkeeper] Ctrl+C — 정지하고 종료합니다")
    finally:
        hal.cleanup()
        run_log.close()


if __name__ == "__main__":
    main()
