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
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from controller import PatrolController, OBSTACLE_STOP_DISTANCE
# 로봇에서는 Supabase를 직접 부르지 않는다(인터넷 없음) — get_my_local_ip만 로컬 함수라 쓴다.
from notify_supabase import get_my_local_ip
from real_hal import RealHAL
from run_logger import JsonlRunLogger
import event_queue
import stream_server

TICK_SECONDS = 0.05  # 20Hz — 실물 초음파 측정(최대 0.03초 x 2)이 있어서 pygame 60Hz보다 낮춤
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

    # 로봇은 자기 핫스팟에 붙어 있어서 인터넷이 없다 — Supabase를 직접 부르지 않고
    # event_queue에 쌓아두면, 랜선으로 인터넷이 되는 PC의 relay.py가 긁어가서 대신 쓴다.
    event_queue.push("local_ip", {"local_ip": get_my_local_ip()})

    # 비동기 작업용 스레드 풀 및 락 초기화 (DB 대신 무거운 로컬 연산 오프로딩에 쓴다)
    db_executor = ThreadPoolExecutor(max_workers=3)
    command_lock = threading.Lock()

    hal = RealHAL(enable_camera=True)
    stream_server.set_camera_angle_callback(hal.set_camera_angle)
    stream_server.set_buzzer_callback(hal.trigger_buzzer)
    # 주의: set_drive_callback / set_qr_scan_callback은 여기서 등록하지 않는다.
    # 아래에서 on_direct_drive(인자 3개) / on_manual_qr_scan으로 다시 등록하는데,
    # 여기서 hal.set_motion(인자 2개)을 먼저 걸어두면 서버가 이미 요청을 받는
    # 그 사이 구간에 인자 개수가 안 맞아 TypeError로 500이 난다.

    command = {"mode": "manual", "speed": 0.0, "turn": 0.0, "cam_pan": 90, "cam_tilt": 90}
    was_manual = True
    last_command_time = time.time()

    # 초음파는 TRIG 핀을 쏘고 ECHO를 재는 방식이라 동시에 두 곳에서 호출하면
    # A가 쏜 펄스를 B가 재는 사고가 난다(30cm 장애물이 900cm로 읽힘 -> 그대로 충돌).
    # HTTP 요청은 각각 별도 스레드에서 오므로, 실제 측정은 제어 루프 한 곳에서만 하고
    # 나머지는 이 캐시를 읽는다. 20Hz로 갱신되니 신선도는 충분하다.
    distance_cache = {"cm": 999.0, "at": 0.0}

    def measure_distance():
        """제어 루프 전용 — 실제로 센서를 쏘고 캐시를 갱신한다."""
        d = hal.read_ultrasonic()
        distance_cache["cm"] = d
        distance_cache["at"] = time.time()
        return d

    def cached_distance():
        """HTTP 스레드용 — 센서를 건드리지 않고 마지막 측정값을 읽는다."""
        return distance_cache["cm"]

    def get_telemetry():
        with command_lock:
            cur_mode = command.get("mode", "manual")
        return {
            "distance_cm": round(cached_distance(), 1),
            "mode": cur_mode,
            "speed": hal.last_speed,
            "turn": hal.last_turn,
            "cam_pan": getattr(hal, "cam_pan", 90),
            "cam_tilt": getattr(hal, "cam_tilt", 90),
        }

    stream_server.set_telemetry_provider(get_telemetry)

    def on_scan(location):
        print(f"[labkeeper] 📸 체크포인트 확인: {location}")
        run_log.write("checkpoint_scanned", checkpoint=location)
        # 어느 물품이 여기 있는지는 중계기가 Supabase를 보고 판단한다 (로봇은 인터넷 없음)
        event_queue.push("audit_scan", {"location": location})

    def on_manual_qr_scan():
        """웹에서 [QR 체크하기] 버튼을 눌렀을 때 온디맨드로 1회 실행."""
        code = hal.scan_qr_now()
        if code:
            on_scan(code)
        return code

    stream_server.set_qr_scan_callback(on_manual_qr_scan)

    last_person_alert_time = 0.0
    PERSON_CHECK_EVERY = 40  # 약 2초마다 체크 — HOG 연산이 무거워서 매 틱마다는 안 돌림
    PERSON_ALERT_COOLDOWN = 20.0  # 사람이 계속 있어도 알림은 20초에 최대 1회만
    person_check_running = threading.Event()  # 이전 체크가 아직 안 끝났으면 겹쳐서 또 제출하지 않기 위한 플래그

    def check_person():
        nonlocal last_person_alert_time
        try:
            if not hal.detect_person():
                return
            now = time.time()
            if (now - last_person_alert_time) < PERSON_ALERT_COOLDOWN:
                return
            last_person_alert_time = now
            print("[labkeeper] 🧍 사람 감지 — SR-03 안전이벤트 큐 적재")
            run_log.write("person_detected", rule_id="SR-03")
            event_queue.push(
                "safety_event",
                {
                    "rule_id": "SR-03",
                    "severity": "HIGH",
                    "note": "실물 Raspbot 순찰 중 카메라 기반 사람 감지(HOG)",
                    "source": "real-raspbot",
                },
                snapshot_bytes=stream_server.get_latest_frame(),
            )
        finally:
            person_check_running.clear()

    last_obstacle_alert_time = 0.0
    OBSTACLE_ALERT_COOLDOWN = 15.0  # 장애물이 계속 있어도 알림 전송은 15초에 최대 1회만 단발 수행

    def on_obstacle(distance):
        nonlocal last_obstacle_alert_time
        now = time.time()
        if (now - last_obstacle_alert_time) < OBSTACLE_ALERT_COOLDOWN:
            return  # 쿨다운 중에는 중복 알림/DB 업로드 스팸 방지

        last_obstacle_alert_time = now
        print(f"[labkeeper] 🛑 장애물 감지({distance:.1f}cm) — 정지 + SR-01 안전이벤트 큐 적재")
        run_log.write("obstacle_detected", distance_cm=round(distance, 2), rule_id="SR-01")
        # 증거 스냅샷을 붙여 큐에 넣는다 (네트워크 없음 — 중계기가 가져가서 DB에 쓴다)
        event_queue.push(
            "safety_event",
            {
                "rule_id": "SR-01",
                "severity": "HIGH",
                "note": f"실물 Raspbot 순찰 중 초음파 장애물 감지 ({distance:.1f}cm)",
                "source": "real-raspbot",
            },
            snapshot_bytes=stream_server.get_latest_frame(),
        )

    def on_obstacle_cleared():
        print("[labkeeper] ✅ 장애물 사라짐 — 순찰 재개")
        run_log.write("obstacle_cleared")

    patrol = PatrolController(
        hal, on_scan=on_scan, on_obstacle=on_obstacle, on_obstacle_cleared=on_obstacle_cleared
    )

    tick = 0

    def on_direct_drive(mode, speed, turn):
        nonlocal was_manual, last_command_time
        with command_lock:
            command["mode"] = mode
            command["speed"] = speed
            command["turn"] = turn
            last_command_time = time.time()
        is_manual = mode == "manual"
        if is_manual != was_manual:
            print(f"[labkeeper] 🎮 모드 전환: {'수동조작' if is_manual else '자동순찰'}")
            run_log.write("mode_changed", mode=mode)
            was_manual = is_manual

        if is_manual:
            # 후진(speed < 0)은 장애물이 가까워도 허용한다 — 안 그러면 벽 앞에서
            # 빠져나올 방법이 없어서 로봇을 손으로 들어 옮겨야 한다.
            if speed > 0 and cached_distance() < OBSTACLE_STOP_DISTANCE:
                hal.stop()
            else:
                hal.set_motion(speed, turn)
        else:
            hal.stop()
        return {
            "mode": mode,
            "speed": hal.last_speed,
            "turn": hal.last_turn,
        }

    stream_server.set_drive_callback(on_direct_drive)

    try:
        while True:
            loop_start = time.time()
            tick += 1

            with command_lock:
                cur_mode = command.get("mode", "manual")
                cur_speed = command.get("speed", 0.0)
                cur_turn = command.get("turn", 0.0)
                cmd_time = last_command_time

            # 수동 조작 시 3초 데드맨 스위치 감시
            if cur_mode == "manual":
                distance = measure_distance()  # 센서를 실제로 쏘는 유일한 지점
                stale = (time.time() - cmd_time) > MANUAL_COMMAND_MAX_AGE_SECONDS
                if stale:
                    hal.stop()  # 3초 동안 웹에서 조이스틱 신호가 없으면 자동 정지
                elif cur_speed > 0 and distance < OBSTACLE_STOP_DISTANCE:
                    hal.stop()  # 전진할 때만 막는다 — 후진 탈출은 허용
                else:
                    hal.set_motion(cur_speed, cur_turn)
            else:
                # 자동 순찰은 PatrolController가 자체적으로 hal.read_ultrasonic()을
                # 호출하므로, 그 결과를 캐시에 반영해 텔레메트리도 최신값을 보게 한다.
                patrol.tick(TICK_SECONDS)
                measure_distance()

            # 주기 스냅샷은 큐에 넣지 않는다 — 중계기가 /snapshot을 직접 긁어가는 게
            # 훨씬 싸다(항상 최신 한 장만 필요한데 큐에 넣으면 메모리만 잡아먹는다).

            if tick % PERSON_CHECK_EVERY == 0 and not person_check_running.is_set():
                person_check_running.set()
                db_executor.submit(check_person)

            if tick % TELEMETRY_LOG_EVERY == 0:
                run_log.write(
                    "telemetry",
                    mode=cur_mode,
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
        db_executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
