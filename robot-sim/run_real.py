"""실제 Raspberry Pi 5 Raspbot에서 실행하는 Physical AI 진입점.

FrameBroker, NCNN 추론 워커, 임무/야간경비 엔진과 RealHAL의 생명주기를 한 곳에서
관리한다. 네트워크나 AI가 실패해도 20 Hz 안전 제어와 수동 정지는 독립적으로 유지한다.

조작(터미널에서 Ctrl+C로 종료 외에는 무인 자동 순찰):
  - 웹 Robot Console에서 수동조작으로 바꾸면 Isaac Sim과 동일하게 반응한다
    (3초 안에 새 명령이 안 오면 dead-man switch로 자동 정지).
  - SPACE/C/R/M/F/N 같은 pygame 키 조작은 실물에는 해당 사항이 없다(화면이 없음).
"""
import datetime
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2

from controller import PatrolController, OBSTACLE_STOP_DISTANCE
from edge_inference import EdgeInferenceWorker, NcnnYoloBackend, draw_detections
from mission_engine import ItemLocationCache, MissionEngine
from night_guard import NightGuardScheduler
# 로봇에서는 Supabase를 직접 부르지 않는다(인터넷 없음) — get_my_local_ip만 로컬 함수라 쓴다.
from notify_supabase import get_my_local_ip
from real_hal import RealHAL
from run_logger import JsonlRunLogger
from dataclasses import asdict as _asdict

import event_queue
import stream_server

# 파이썬은 기본적으로 한 스레드가 5ms 동안 GIL을 쥐고 있다가 넘긴다. 이 프로세스는
# 제어 루프(초음파 측정) · AI 추론 · 웹 명령을 받는 HTTP 핸들러가 한 프로세스에서
# 같이 도는데, 5ms는 서보 명령이 밀려 카메라가 떨릴 만큼 길다. 1ms로 줄여 명령
# 스레드가 더 자주 끼어들 수 있게 한다.
sys.setswitchinterval(0.001)

TICK_SECONDS = 0.05  # 20Hz — 실물 초음파 측정(최대 0.03초 x 2)이 있어서 60Hz보다 낮춤
TELEMETRY_LOG_EVERY = 20  # 약 1초마다 텔레메트리 기록
MANUAL_COMMAND_MAX_AGE_SECONDS = 3.0  # dead-man switch 기준

_ROBOT_SIM_ROOT = os.path.dirname(os.path.abspath(__file__))


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _command_age_seconds(command):
    """updated_at을 못 읽으면 무조건 "끊김"으로 처리."""
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
    shutdown_requested = threading.Event()

    def request_shutdown(signum, _frame):
        print(f"[labkeeper] 종료 신호 {signum} 수신 — 안전 정지합니다")
        shutdown_requested.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
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

    # 단일 YOLO11n NCNN 모델은 로봇 안에서 직접 실행한다. Shadow Mode에서는
    # 감지 결과를 기록/표시만 하고 모터·부저를 자동으로 움직이지 않는다.
    ai_worker = None
    ai_runtime_status = {
        "running": False,
        "mode": "disabled",
        "backend": "ncnn",
        "model_scope": "lab-items+person",
    }
    ai_last_person_event = {"at": 0.0}
    # on_ai_result가 사람을 순정 모델로 교체한 "보정 후" 결과. /ai/status가 이걸 읽어야
    # 화면(박스)과 상태(목록)가 같은 내용을 말한다 — 안 그러면 스트림엔 없는 사람이
    # 상태 목록에는 남아 있는 식으로 어긋난다.
    ai_corrected = {"detections": None}
    ai_person_cooldown = float(os.environ.get("LABKEEPER_AI_PERSON_COOLDOWN", "20"))
    ai_model_dir = os.environ.get(
        "LABKEEPER_AI_MODEL_DIR",
        os.path.join(
            _ROBOT_SIM_ROOT,
            "ai_vision",
            "models",
            "edge",
            "lab_guardian_physical_ai_ncnn",
        ),
    )

    # 사람은 커스텀 모델이 아니라 COCO 순정 모델이 판정한다.
    # 커스텀 모델은 사람 인스턴스 204개로만 파인튜닝돼서, 원래 COCO 6만여 장으로
    # 학습돼 있던 사람 판별 경계가 뭉개졌다(catastrophic forgetting).
    # 같은 검증셋 84장으로 측정한 결과:
    #     커스텀  정밀도 0.356 / 재현율 0.696 / F1 0.471 / 오탐 29
    #     순정    정밀도 0.640 / 재현율 0.696 / F1 0.667 / 오탐  9
    # 찾는 능력(재현율)은 같은데 커스텀만 오탐이 3배 이상이라, 사람 판정만 순정에 맡긴다.
    ai_person_model_dir = os.environ.get(
        "LABKEEPER_AI_PERSON_MODEL_DIR",
        os.path.join(
            _ROBOT_SIM_ROOT, "ai_vision", "models", "edge", "person_coco_ncnn"
        ),
    )

    if _env_bool("LABKEEPER_AI_ENABLED", True):
        try:
            ai_backend = NcnnYoloBackend.from_manifest(
                ai_model_dir,
                confidence=float(os.environ.get("LABKEEPER_AI_CONFIDENCE", "0.40")),
                num_threads=int(os.environ.get("LABKEEPER_AI_THREADS", "2")),
            )

            # 사람 전용 백엔드. 없으면(미배포 등) 조용히 비활성화하고 물품 탐지는 계속한다.
            ai_person_backend = None
            try:
                ai_person_backend = NcnnYoloBackend.from_manifest(
                    ai_person_model_dir,
                    confidence=float(os.environ.get("LABKEEPER_AI_PERSON_CONFIDENCE", "0.40")),
                    num_threads=int(os.environ.get("LABKEEPER_AI_THREADS", "2")),
                )
                print(f"[labkeeper] 사람 판정: COCO 순정 모델 / {ai_person_model_dir}")
            except Exception as person_exc:
                print(f"[labkeeper] 사람 전용 모델 없음 — 커스텀 모델의 person을 그대로 씀: {person_exc}")

            # 아무도 AI 스트림을 안 볼 때 오버레이를 만드는 최소 간격(초).
            AI_IDLE_DRAW_INTERVAL_S = 1.0
            ai_last_draw = {"at": 0.0}

            def on_ai_result(snapshot, source_frame):
                # 커스텀 모델 결과에서 person은 버린다 — 오탐이 3배라 신뢰할 수 없다.
                # 물품 탐지만 남기고, 사람은 아래에서 순정 모델로 다시 판정한다.
                detections = [d for d in snapshot.detections if d.class_name != "person"]

                if ai_person_backend is not None:
                    try:
                        # 이 모델은 COCO 80클래스를 이미 다 계산하므로 전부 취한다.
                        # 걸러내는 건 연산을 아끼지 못하고 정보만 버리는 것이다.
                        # 구조: COCO 80클래스(일상 전반) + 커스텀 모델의 실험실 물품 10종.
                        detections.extend(ai_person_backend.detect(source_frame))
                    except Exception as person_err:
                        # 사람 판정이 실패해도 물품 탐지와 스트림은 계속 살려둔다.
                        print(f"[labkeeper] 사람 판정 실패(무시하고 계속): {person_err}")
                else:
                    # 순정 모델이 없으면 어쩔 수 없이 커스텀의 person을 쓴다.
                    detections.extend(d for d in snapshot.detections if d.class_name == "person")

                # 박스를 그려 넣는 일(2배 확대 + 고품질 JPEG)은 이 루프에서 제일
                # 비싸다. 그런데 /ai/stream을 아무도 안 보고 있으면 그대로 버려진다.
                # 보는 사람이 있을 때만 그리고, 없으면 /ai/snapshot이 너무 낡지
                # 않게 1초에 한 장만 만든다. 탐지 자체(아래 ai_corrected)는 경비
                # 판단에 쓰이므로 항상 갱신한다.
                def encode_annotated():
                    """박스를 그려 넣은 JPEG 한 장. 실패하면 None."""
                    ok, buf = cv2.imencode(
                        ".jpg", draw_detections(source_frame, detections),
                        [int(cv2.IMWRITE_JPEG_QUALITY), 85, int(cv2.IMWRITE_JPEG_OPTIMIZE), 0],
                    )
                    return buf.tobytes() if ok else None

                now_draw = time.time()
                fresh_jpeg = None
                if (stream_server.ai_has_viewers()
                        or now_draw - ai_last_draw["at"] >= AI_IDLE_DRAW_INTERVAL_S):
                    ai_last_draw["at"] = now_draw
                    fresh_jpeg = encode_annotated()
                    if fresh_jpeg:
                        stream_server.set_ai_frame(fresh_jpeg)

                ai_corrected["detections"] = [_asdict(d) for d in detections]

                people = [item for item in detections if item.class_name == "person"]
                now = time.time()
                if people and now - ai_last_person_event["at"] >= ai_person_cooldown:
                    ai_last_person_event["at"] = now
                    confidence = max(item.confidence for item in people)
                    print(f"[labkeeper] AI Shadow 사람 관찰 ({confidence:.0%})")
                    run_log.write(
                        "ai_person_observed",
                        confidence=round(confidence, 4),
                        mode="shadow",
                    )
                    event_queue.push(
                        "safety_event",
                        {
                            "rule_id": "SR-03-SHADOW",
                            "severity": "MEDIUM",
                            "note": f"라즈봇 로컬 AI Shadow Mode 사람 관찰 ({confidence:.0%})",
                            "source": "real-raspbot-edge-ai",
                            "shadow_mode": True,
                        },
                        # 증거 사진은 이 프레임에서 새로 만든다. 스트림용 인코딩을
                        # 건너뛴 프레임일 수도 있어서 그때는 여기서 한 장 만든다 —
                        # 쿨다운이 걸려 있어 자주 일어나지 않는다.
                        snapshot_bytes=fresh_jpeg or encode_annotated(),
                    )

            ai_worker = EdgeInferenceWorker(
                hal.capture_frame,
                ai_backend,
                target_fps=float(os.environ.get("LABKEEPER_AI_TARGET_FPS", "12")),
                result_callback=on_ai_result,
            )
            ai_worker.start()
            ai_runtime_status.update({"mode": "shadow", "model_dir": ai_model_dir})
            print(f"[labkeeper] 로컬 Physical AI 시작: NCNN Shadow Mode / {ai_model_dir}")
        except Exception as exc:
            ai_runtime_status.update({"mode": "unavailable", "error": f"{type(exc).__name__}: {exc}"})
            print(f"[labkeeper] 로컬 Physical AI 비활성: {ai_runtime_status['error']}")

    def get_ai_status():
        if ai_worker is None:
            return {"status": "error", **ai_runtime_status}
        worker_status = ai_worker.status()
        latest = worker_status.get("latest") or {}
        # 사람이 순정 모델로 교체된 뒤의 목록이 있으면 그걸 쓴다.
        if ai_corrected["detections"] is not None:
            latest = {**latest, "detections": ai_corrected["detections"]}
        class_names_kr = {
            "microscope": "현미경",
            "centrifuge": "원심분리기",
            "pipette": "피펫",
            "beaker": "비커",
            "flask": "플라스크",
            "reagent_bottle": "시약병",
            "fire_extinguisher": "소화기",
            "spill_kit": "유출 대응 키트",
            "flammable_cabinet": "인화성 물질 캐비닛",
            "biohazard_bin": "생물학적 폐기물통",
            "person": "사람",
            # 순정 COCO 모델이 같이 잡아주는 일상 물품 (학습 없이 얻는 것)
            "chair": "의자", "couch": "소파", "potted plant": "화분",
            "dining table": "책상", "bed": "침대", "toilet": "변기", "sink": "싱크대",
            "tv": "모니터", "laptop": "노트북", "mouse": "마우스", "remote": "리모컨",
            "keyboard": "키보드", "cell phone": "휴대폰", "microwave": "전자레인지",
            "oven": "오븐", "refrigerator": "냉장고", "clock": "시계",
            "backpack": "가방", "handbag": "핸드백", "umbrella": "우산",
            "book": "책", "vase": "꽃병", "scissors": "가위",
            "bottle": "병", "cup": "컵", "bowl": "그릇", "toothbrush": "칫솔",
        }
        detections = [
            {
                **detection,
                "name_kr": class_names_kr.get(detection["class_name"], detection["class_name"]),
                "confidence_percent": round(detection["confidence"] * 100),
                "type": "PERSON" if detection["class_name"] == "person" else "OBJECT",
            }
            for detection in latest.get("detections", [])
        ]
        return {
            "status": "ok" if worker_status.get("running") and not worker_status.get("error") else "error",
            **ai_runtime_status,
            **worker_status,
            "detections": detections,
            "guard_action": "SHADOW_PERSON_VISIBLE" if any(
                item["class_name"] == "person" for item in detections
            ) else "SHADOW_MONITORING",
        }

    stream_server.set_ai_status_provider(get_ai_status)

    location_cache = ItemLocationCache(
        os.environ.get(
            "LABKEEPER_ITEM_CACHE",
            os.path.join(_ROBOT_SIM_ROOT, "config", "item_location_cache.json"),
        )
    )
    mission_engine = MissionEngine(location_cache)

    def on_item_locations_update(payload):
        result = location_cache.replace(payload.get("items"), payload.get("revision"))
        run_log.write("item_location_cache_updated", **result)
        return result

    stream_server.set_item_location_callbacks(
        update=on_item_locations_update,
        status=location_cache.status,
    )

    def on_guide_start(params):
        result = mission_engine.start(
            request_id=params.get("request_id") or params.get("loan_id"),
            item_id=params.get("item_id"),
            mission_type=params.get("mission_type") or params.get("mode") or "pickup",
        )
        run_log.write(
            "guide_requested",
            request_id=result["request_id"],
            item_id=result["item_id"],
            status=result["status"],
            direct_from_previous=result["direct_from_previous"],
        )
        return result

    def on_guide_finish(status):
        result = mission_engine.finish(status)
        run_log.write("guide_finished", status=status, item_id=result.get("item_id"))
        return result

    stream_server.set_guide_callbacks(
        start=on_guide_start,
        status=mission_engine.status,
        finish=on_guide_finish,
    )

    detection_class_by_keyword = {
        "현미경": "microscope",
        "원심": "centrifuge",
        "피펫": "pipette",
        "비커": "beaker",
        "플라스크": "flask",
        "시약": "reagent_bottle",
        "에탄올": "reagent_bottle",
        "소화기": "fire_extinguisher",
        "유출": "spill_kit",
        "인화": "flammable_cabinet",
        "폐기물": "biohazard_bin",
    }

    def verify_checkout(params):
        if ai_worker is None:
            return {"verdict": "unavailable", "reason": "로봇 내부 AI 엔진을 사용할 수 없습니다."}
        snapshot = ai_worker.latest()
        if snapshot is None or time.time() - snapshot.timestamp > 1.0:
            return {"verdict": "inconclusive", "reason": "최신 AI 프레임이 없습니다."}
        item = location_cache.resolve(params.get("item_id")) if params.get("item_id") else None
        expected_name = (item or {}).get("item_name", "")
        expected_class = next(
            (class_name for keyword, class_name in detection_class_by_keyword.items() if keyword in expected_name),
            None,
        )
        visible_items = [
            detection for detection in snapshot.detections
            if detection.class_name != "person" and detection.confidence >= 0.45
        ]
        rendered = [
            {
                "class_name": detection.class_name,
                "confidence": round(detection.confidence, 4),
            }
            for detection in visible_items
        ]
        if expected_class is None:
            return {
                "verdict": "inconclusive",
                "reason": "이 물품은 현재 11종 통합 모델의 개별 클래스와 매핑되지 않습니다.",
                "detected_items": rendered,
            }
        expected = [item for item in visible_items if item.class_name == expected_class]
        unexpected = [item for item in visible_items if item.class_name != expected_class]
        if unexpected:
            return {
                "verdict": "blocked",
                "reason": "예약 물품 외 다른 물품이 함께 감지됐습니다.",
                "expected_class": expected_class,
                "detected_items": rendered,
            }
        if not expected:
            return {
                "verdict": "inconclusive",
                "reason": "예약 물품을 카메라 중앙에서 확인하지 못했습니다.",
                "expected_class": expected_class,
                "detected_items": rendered,
            }
        return {
            "verdict": "clear",
            "reason": "예약 물품 한 종류만 확인했습니다. 최종 대여 처리는 QR로 검증합니다.",
            "expected_class": expected_class,
            "detected_items": rendered,
        }

    stream_server.set_checkout_verify_callback(verify_checkout)

    def classify_obstacle_from_edge_ai():
        if ai_worker is None:
            return "object"
        snapshot = ai_worker.latest()
        if snapshot is None or time.time() - snapshot.timestamp > 0.75:
            return "object"
        for detection in snapshot.detections:
            if detection.class_name != "person" or detection.confidence < 0.40:
                continue
            x1, _y1, x2, _y2 = detection.box
            center_x = (x1 + x2) / 2.0
            if 64 <= center_x <= 256:
                return "person"
        return "object"

    hal.set_obstacle_classifier(classify_obstacle_from_edge_ai)

    night_guard = NightGuardScheduler()
    stream_server.set_guard_callbacks(
        status=night_guard.status,
        configure=night_guard.configure,
        trigger=night_guard.trigger,
    )
    allow_ai_actuation = _env_bool("LABKEEPER_AI_ACTUATION", False)
    latest_guard = night_guard.status()
    last_guard_transition_id = latest_guard["transition_id"]
    control_source = {"value": "manual"}

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
        mission = mission_engine.status()
        return {
            "distance_cm": round(cached_distance(), 1),
            "mode": cur_mode,
            "speed": hal.last_speed,
            "turn": hal.last_turn,
            "cam_pan": getattr(hal, "cam_pan", 90),
            "cam_tilt": getattr(hal, "cam_tilt", 90),
            "ai": {
                "mode": get_ai_status().get("mode", "unavailable"),
                "fps": get_ai_status().get("actual_fps", 0.0),
            },
            "mission": {
                "status": mission.get("status", "idle"),
                "item_id": mission.get("item_id"),
                "shelf_code": mission.get("shelf_code"),
            },
            "night_guard": night_guard.status(),
            "control_source": control_source["value"],
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

    last_obstacle_alert_time = 0.0
    OBSTACLE_ALERT_COOLDOWN = 15.0  # 장애물이 계속 있어도 알림 전송은 15초에 최대 1회만 단발 수행

    # 벽·책상처럼 원래 거기 있는 물체는 "사건"이 아니다. 쿨다운만 걸면 로봇이 벽 앞에
    # 서 있는 동안 15초마다 계속 신고해서(실측: SR-01 194건) 관리자 화면이 도배된다.
    # 그래서 한 번 신고한 장애물은 "사라졌다가 다시 나타날 때"만 다시 신고한다.
    obstacle_reported = {"active": False}

    def on_obstacle(distance):
        nonlocal last_obstacle_alert_time
        now = time.time()
        if obstacle_reported["active"]:
            return  # 이미 신고한 그 장애물이 아직 앞에 있는 것 — 새 사건이 아니다
        if (now - last_obstacle_alert_time) < OBSTACLE_ALERT_COOLDOWN:
            return  # 쿨다운 중에는 중복 알림/DB 업로드 스팸 방지

        obstacle_reported["active"] = True
        last_obstacle_alert_time = now

        # 초음파는 "20cm 앞에 뭔가 있다"까지만 안다. 그게 벽인지 사람인지 넘어진 의자인지는
        # 카메라가 이미 보고 있으므로, 같은 순간의 탐지 결과를 붙여 무엇이 막았는지 남긴다.
        # 사람이 막고 있으면 심각도를 올린다 — 벽 앞에 선 것과 사람 앞에 선 것은 다른 사건이다.
        seen = ai_corrected["detections"] or []
        labels = []
        for d in sorted(seen, key=lambda x: -x.get("confidence", 0))[:3]:
            labels.append(f"{d.get('class_name')} {round(d.get('confidence', 0) * 100)}%")
        what = ", ".join(labels) if labels else "식별된 물체 없음"
        person_blocking = any(d.get("class_name") == "person" for d in seen)
        severity = "HIGH" if person_blocking else "MEDIUM"

        print(f"[labkeeper] 🛑 장애물 감지({distance:.1f}cm) — 정지 + SR-01 ({what})")
        run_log.write(
            "obstacle_detected",
            distance_cm=round(distance, 2),
            rule_id="SR-01",
            detected=what,
        )
        # 증거 스냅샷을 붙여 큐에 넣는다 (네트워크 없음 — 중계기가 가져가서 DB에 쓴다)
        event_queue.push(
            "safety_event",
            {
                "rule_id": "SR-01",
                "severity": severity,
                "note": f"실물 Raspbot 순찰 중 장애물 감지 ({distance:.1f}cm) — 카메라 인식: {what}",
                "source": "real-raspbot",
            },
            snapshot_bytes=stream_server.get_latest_frame(),
        )

    def on_obstacle_cleared():
        # 장애물이 치워졌으니, 다음에 뭔가 나타나면 그건 새 사건으로 신고한다.
        obstacle_reported["active"] = False
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
        while not shutdown_requested.is_set():
            loop_start = time.time()
            tick += 1

            with command_lock:
                cur_mode = command.get("mode", "manual")
                cur_speed = command.get("speed", 0.0)
                cur_turn = command.get("turn", 0.0)
                cmd_time = last_command_time

            # 수동 조작 시 3초 데드맨 스위치 감시
            if cur_mode == "manual":
                control_source["value"] = "manual"
                distance = measure_distance()  # 센서를 실제로 쏘는 유일한 지점
                stale = (time.time() - cmd_time) > MANUAL_COMMAND_MAX_AGE_SECONDS
                if stale:
                    hal.stop()  # 3초 동안 웹에서 조이스틱 신호가 없으면 자동 정지
                elif cur_speed > 0 and distance < OBSTACLE_STOP_DISTANCE:
                    hal.stop()  # 전진할 때만 막는다 — 후진 탈출은 허용
                else:
                    hal.set_motion(cur_speed, cur_turn)
            else:
                distance = measure_distance()
                ai_person = False
                if allow_ai_actuation and ai_worker is not None:
                    latest_ai = ai_worker.latest()
                    ai_person = bool(
                        latest_ai
                        and time.time() - latest_ai.timestamp <= 0.75
                        and any(
                            item.class_name == "person" and item.confidence >= 0.45
                            for item in latest_ai.detections
                        )
                    )
                stationary_guard = latest_guard.get("state") in {"standby", "verifying"}
                motion = tick % 10 == 0 and stationary_guard and hal.detect_motion()
                latest_guard = night_guard.update(
                    sonar_cm=distance,
                    motion=motion,
                    person=ai_person,
                )
                if latest_guard["transition_id"] != last_guard_transition_id:
                    last_guard_transition_id = latest_guard["transition_id"]
                    run_log.write(
                        "night_guard_transition",
                        state=latest_guard["state"],
                        reason=latest_guard.get("reason", ""),
                    )
                if mission_engine.should_drive():
                    control_source["value"] = "item_guide"
                    patrol.tick(TICK_SECONDS, distance)
                elif latest_guard.get("active") and latest_guard.get("should_move"):
                    control_source["value"] = "night_guard"
                    patrol.tick(TICK_SECONDS, distance)
                else:
                    # 주간 기본은 대여 보조 대기다. 임무 없이 상시 순찰하지 않는다.
                    control_source["value"] = "rental_assist_idle"
                    hal.stop()

            # 주기 스냅샷은 큐에 넣지 않는다 — 중계기가 /snapshot을 직접 긁어가는 게
            # 훨씬 싸다(항상 최신 한 장만 필요한데 큐에 넣으면 메모리만 잡아먹는다).

            if tick % TELEMETRY_LOG_EVERY == 0:
                run_log.write(
                    "telemetry",
                    mode=cur_mode,
                    command_speed=hal.last_speed,
                    command_turn=hal.last_turn,
                )

            elapsed = time.time() - loop_start
            time.sleep(max(0.0, TICK_SECONDS - elapsed))
    finally:
        if ai_worker is not None:
            ai_worker.stop()
        hal.cleanup()
        run_log.close()
        db_executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
