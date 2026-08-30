"""실제 Raspberry Pi 5 Raspbot에서 실행하는 Physical AI 진입점.

FrameBroker, NCNN 추론 워커, 임무/야간경비 엔진과 RealHAL의 생명주기를 한 곳에서
관리한다. 네트워크나 AI가 실패해도 20 Hz 안전 제어와 수동 정지는 독립적으로 유지한다.

조작(터미널에서 Ctrl+C로 종료 외에는 무인 자동 순찰):
  - 웹 Robot Console에서 수동조작으로 바꾸면 Isaac Sim과 동일하게 반응한다
    (3초 안에 새 명령이 안 오면 dead-man switch로 자동 정지).
  - SPACE/C/R/M/F/N 같은 pygame 키 조작은 실물에는 해당 사항이 없다(화면이 없음).
"""
import datetime
import math
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2

from controller import PatrolController, OBSTACLE_STOP_DISTANCE, speed_cap_for_distance
from edge_inference import EdgeInferenceWorker, NcnnYoloBackend, draw_detections
from mission_engine import ItemLocationCache, MissionEngine
from night_guard import NightGuardScheduler
# 로봇에서는 Supabase를 직접 부르지 않는다(인터넷 없음) — get_my_local_ip만 로컬 함수라 쓴다.
import notify_supabase
from notify_supabase import get_my_local_ip
from real_hal import RealHAL
from run_logger import JsonlRunLogger
from dataclasses import asdict as _asdict

import event_queue
from route_recorder import RouteRecorder, RoutePlayer, load_route, list_routes
from patrol import PatrolRunner, load_map, list_maps
import shelf_map
from odometry import Odometry, load_model, save_model
import calibrate_motion
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
    stream_server.set_camera_direction_callback(hal.set_camera_direction)
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
            "lab_guardian_unified90_ncnn",
        ),
    )

    # 예전에는 모델을 두 개 돌렸다. 실험실 데이터 2,477장'만'으로 재학습한 커스텀
    # 모델이 COCO 80클래스를 잊어버려서(catastrophic forgetting) 사람 오탐이 3배가
    # 됐고, 사람 판정을 COCO 순정 모델에 따로 맡겨야 했기 때문이다. 한 프레임에
    # 추론이 두 번 돌아 66.4ms 가 들었고 그게 발열의 주범이었다.
    #
    # 2026-08-30, COCO 6만 장을 리플레이로 섞고 백본 앞 10층을 얼려서 90클래스
    # 단일 모델로 다시 학습했다. 실측 결과 두 축 모두 기준을 넘었다:
    #     COCO      0.4786 -> 0.4579 (-4.3%)   1차 시도는 -33% 라 폐기했었다
    #     실험실    0.6244 -> 0.7352 (+18%)
    #     한 주기   66.4ms -> 42.3ms (-36%)    입력은 오히려 320 -> 416 으로 키움
    #     온도      47.4 -> 44.6도
    # 그래서 사람 전용 모델은 더 이상 쓰지 않는다. 되돌릴 일이 생기면
    # LABKEEPER_AI_PERSON_MODEL_DIR 를 지정하면 예전 2모델 구성으로 돌아간다.
    ai_person_model_dir = os.environ.get("LABKEEPER_AI_PERSON_MODEL_DIR", "")

    if _env_bool("LABKEEPER_AI_ENABLED", True):
        try:
            ai_backend = NcnnYoloBackend.from_manifest(
                ai_model_dir,
                confidence=float(os.environ.get("LABKEEPER_AI_CONFIDENCE", "0.40")),
                num_threads=int(os.environ.get("LABKEEPER_AI_THREADS", "4")),
            )

            # 통합 모델이 사람까지 보므로 평소에는 두 번째 백엔드를 쓰지 않는다.
            # 환경변수로 경로를 주면 예전 2모델 구성으로 되돌릴 수 있다.
            ai_person_backend = None
            if ai_person_model_dir:
                try:
                    ai_person_backend = NcnnYoloBackend.from_manifest(
                        ai_person_model_dir,
                        confidence=float(os.environ.get("LABKEEPER_AI_PERSON_CONFIDENCE", "0.40")),
                        num_threads=int(os.environ.get("LABKEEPER_AI_THREADS", "4")),
                    )
                    print(f"[labkeeper] 사람 판정: 별도 모델 사용 / {ai_person_model_dir}")
                except Exception as person_exc:
                    print(f"[labkeeper] 사람 전용 모델 로드 실패 — 통합 모델로 계속: {person_exc}")
            else:
                print(f"[labkeeper] 통합 90클래스 모델 단독 / {ai_model_dir}")

            # 아무도 AI 스트림을 안 볼 때 오버레이를 만드는 최소 간격(초).
            AI_IDLE_DRAW_INTERVAL_S = 1.0
            ai_last_draw = {"at": 0.0}

            # 품질 85 는 카메라가 320x240 이던 시절 2배 확대해서 보느라 올려둔
            # 값이다. 지금은 640x480 원본을 그대로 쓰므로 확대가 없고 85 는 과하다.
            # 실측: 85 에서 한 장 51KB 로 일반 스트림(24KB)의 2.1배라, 두 스트림을
            # 같이 켜면 브라우저가 MJPEG 두 개를 디코딩하느라 버거워한다.
            AI_JPEG_QUALITY = int(os.environ.get("LABKEEPER_AI_JPEG_QUALITY", "62"))
            ai_latest_boxes = {"value": []}

            def overlay_encoder(frame):
                """카메라 루프(30fps)가 부르는 오버레이 인코더.

                추론은 8fps 라 네모는 최대 125ms 뒤처지지만, 영상 자체는 30fps 로
                흐른다. 예전에는 추론된 프레임에만 그려서 화면까지 8fps 였다.
                """
                boxes = ai_latest_boxes["value"]
                ok, buf = cv2.imencode(
                    ".jpg", draw_detections(frame, boxes),
                    [int(cv2.IMWRITE_JPEG_QUALITY), AI_JPEG_QUALITY,
                     int(cv2.IMWRITE_JPEG_OPTIMIZE), 0],
                )
                return buf.tobytes() if ok else None

            def on_ai_result(snapshot, source_frame):
                # 통합 모델은 사람·일상물체·실험실물품을 한 번에 본다. 따로 거를 게 없다.
                # 별도 사람 모델을 쓰는 구성일 때만 person 을 버리고 그쪽에 맡긴다.
                if ai_person_backend is None:
                    detections = list(snapshot.detections)
                else:
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
                    """박스와 마커를 그려 넣은 JPEG 한 장. 실패하면 None.

                    마커를 같이 그리는 이유는 "지금 마커가 보이는지"를 화면으로
                    바로 확인하기 위해서다. 로그 숫자만으로는 안 보이는 건지
                    보이는데 계산이 틀린 건지 구분이 안 된다.
                    """
                    seen_markers = []
                    if marker_overlay["locator"] is not None:
                        try:
                            seen_markers = marker_overlay["locator"].find(source_frame)
                        except Exception:
                            seen_markers = []
                    # QR 도 같이 그린다. "QR 인식이 안 된다"고 할 때, 네모가
                    # 그려지면 각도·거리 문제이고 안 그려지면 아예 안 보이는
                    # 것이라 원인이 바로 갈린다.
                    try:
                        seen_qrs = hal.find_qr_boxes(source_frame)
                    except Exception:
                        seen_qrs = []
                    ok, buf = cv2.imencode(
                        ".jpg", draw_detections(source_frame, detections,
                                                markers=seen_markers, qrs=seen_qrs),
                        [int(cv2.IMWRITE_JPEG_QUALITY), AI_JPEG_QUALITY, int(cv2.IMWRITE_JPEG_OPTIMIZE), 0],
                    )
                    return buf.tobytes() if ok else None

                # 보는 사람이 있으면 카메라 루프가 30fps 로 오버레이를 만든다
                # (아래 set_ai_overlay_encoder). 여기서는 아무도 안 볼 때
                # /ai/snapshot 이 너무 낡지 않게 1초에 한 장만 만들어 둔다.
                now_draw = time.time()
                fresh_jpeg = None
                if (not stream_server.ai_has_viewers()
                        and now_draw - ai_last_draw["at"] >= AI_IDLE_DRAW_INTERVAL_S):
                    ai_last_draw["at"] = now_draw
                    fresh_jpeg = encode_annotated()
                    if fresh_jpeg:
                        stream_server.set_ai_frame(fresh_jpeg)

                ai_corrected["detections"] = [_asdict(d) for d in detections]
                # 카메라 루프가 매 프레임 얹을 수 있게 최신 탐지를 넘겨둔다.
                ai_latest_boxes["value"] = detections

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
            # 카메라 루프가 30fps 로 오버레이를 만들도록 연결한다.
            hal.set_ai_overlay_encoder(overlay_encoder)
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

    # 배달 상태와 실행 함수. 실행 함수는 한참 아래(순찰 설정 뒤)에서 채워진다 -
    # patrol·odometry 가 있어야 만들 수 있기 때문이다. 그런데 HTTP 서버는 그보다
    # 먼저 뜨므로, 그 사이에 대여 요청이 오면 아직 없는 이름을 부르게 된다.
    # 홀더에 담아두고 "아직 준비 안 됐다"를 정상 응답으로 돌려준다.
    delivery = {"running": False, "item_id": None, "shelf": None,
                "phase": "idle", "qr": None, "error_cm": None, "message": ""}
    driver = {"start": None}

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

        # 여기서 실제로 운전을 건다. mission_engine 은 "무엇을 가지러 가는가"를
        # 기록할 뿐이고, 예전에는 physical_route(티치앤리피트)가 실행을 맡았는데
        # 그 방식은 오차가 쌓여 못 쓴다. 지금은 선반 좌표로 직접 간다.
        #
        # 실패해도 안내 기록 자체는 남긴다 - 대여는 성립했고 로봇만 못 간 것이라,
        # 여기서 예외를 던지면 웹의 대여 흐름 전체가 막힌다.
        try:
            if driver["start"] is None:
                raise RuntimeError("주행 준비가 아직 끝나지 않았다")
            drive = driver["start"](int(result["item_id"]), from_home=True)
            result["drive"] = drive
            if "shelf" in drive:
                result["shelf_code"] = drive["shelf"]["code"]
                result["target_x"] = drive["shelf"]["x_cm"]
                result["target_y"] = drive["shelf"]["y_cm"]
        except Exception as e:
            result["drive"] = {"error": str(e)}
            print(f"[guide] 주행을 못 걸었다(안내 기록은 유지): {e}")
        return result

    def on_guide_finish(status):
        result = mission_engine.finish(status)
        run_log.write("guide_finished", status=status, item_id=result.get("item_id"))
        return result

    def on_guide_status():
        """안내 상태에 실제 주행 진행을 얹어 준다.

        웹이 mission 과 patrol 을 따로 폴링하면 둘이 어긋난 순간이 보인다
        (도착했는데 mission 은 아직 navigating 이라거나). 한 군데서 같이 낸다.
        """
        st = mission_engine.status()
        st["drive"] = dict(delivery)
        pose = odometry.pose()
        st["drive"]["x_cm"] = pose["x_cm"]
        st["drive"]["y_cm"] = pose["y_cm"]
        return st

    stream_server.set_guide_callbacks(
        start=on_guide_start,
        status=on_guide_status,
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

    # AI 오버레이가 마커를 그릴 수 있게 인식기를 여기 담아둔다. 인식기 자체는
    # 아래(순찰 설정)에서 만들어지는데, 오버레이는 그보다 먼저 정의된다.
    marker_overlay = {"locator": None}

    # 자율 주행(순찰·경로 재생·모션 측정)이 바퀴를 잡고 있는 동안 메인 루프가
    # 끼어들면 안 된다. 수동 모드의 메인 루프는 웹 조이스틱 신호가 3초 없으면
    # 매 틱 hal.stop() 을 부르는데(데드맨 스위치), 그게 순찰 명령을 초당 10번
    # 지워버린다. 실제로 이것 때문에 순찰이 "소리만 나고 거의 안 움직였다".
    motion_owner = {"name": None}

    class WheelLease:
        """with 블록 동안 바퀴 소유권을 가져간다."""

        def __init__(self, name):
            self.name = name

        def __enter__(self):
            motion_owner["name"] = self.name
            return self

        def __exit__(self, *exc):
            motion_owner["name"] = None
            hal.stop()
            return False

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
            # 배달 나가서 기다리는 중이었다면 볼일이 끝난 것이다. 남은 대기
            # 시간을 채우지 않고 바로 대기 자리로 돌려보낸다. 시간이 아니라
            # "일이 끝났다"를 신호로 삼는 쪽이 맞다.
            if delivery.get("running") and delivery.get("phase") == "waiting":
                delivery["recall"] = True
                print("[deliver] QR 확인됨 — 대기 자리로 복귀시킨다")
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

        # 녹화 중이면 이 명령을 경로에 쌓는다. 녹화가 아니면 아무 일도 안 한다.
        route_recorder.on_drive(speed, turn)

        if is_manual:
            # 후진(speed < 0)은 장애물이 가까워도 허용한다 — 안 그러면 벽 앞에서
            # 빠져나올 방법이 없어서 로봇을 손으로 들어 옮겨야 한다.
            if speed > 0:
                # 임계값에서 갑자기 멈추면 관성으로 더 간다(실측: PWM 60에서
                # 4.5cm). 거리에 따라 미리 감속해서 그 여유를 만든다.
                cap = speed_cap_for_distance(cached_distance())
                if cap <= 0:
                    hal.stop()
                else:
                    hal.set_motion(min(speed, cap), turn)
            else:
                hal.set_motion(speed, turn)
        else:
            hal.stop()
        return {
            "mode": mode,
            "speed": hal.last_speed,
            "turn": hal.last_turn,
        }

    # ── 경로 녹화·재생 (좌표 순찰 2단계) ──────────────────────────────
    # 마커 인식기. 없어도 녹화·재생은 되지만 위치 보정은 못 한다.
    marker_locator = None
    try:
        from marker_locator import MarkerLocator
        marker_locator = MarkerLocator()
        print(f"[route] 마커 인식기 준비 · 마커 {marker_locator.marker_size_mm:.0f}mm "
              f"· 보정계수 {marker_locator.scale:.4f}")
    except Exception as marker_exc:
        print(f"[route] 마커 인식기 없음 — 위치 보정 없이 진행: {marker_exc}")

    route_recorder = RouteRecorder()
    route_player = RoutePlayer(
        hal,
        distance_fn=cached_distance,
        stop_distance=OBSTACLE_STOP_DISTANCE,
        speed_cap_fn=speed_cap_for_distance,
        # 재생 중 마커를 보고 위치를 되돌리는 데 쓴다. 마커 인식기가 없으면
        # 보정 없이 녹화한 구간만 재생한다.
        marker_fn=(lambda: marker_locator.find(hal.capture_frame())) if marker_locator else None,
    )
    route_play_thread = {"t": None}

    # 녹화 중 마커가 보이면 자동으로 찍는다. 사람이 주행하면서 매번 버튼을
    # 누르는 건 현실적이지 않고, 놓치면 그 지점의 보정 기회가 사라진다.
    auto_mark = {"stop": None}

    def _auto_mark_loop(stop_event):
        """마커가 보이면 경로에 새긴다. 같은 마커를 연달아 찍지 않는다."""
        last_id = None
        last_at = 0.0
        last_segments = -1
        while not stop_event.is_set():
            try:
                found = marker_locator.find(hal.capture_frame()) if marker_locator else []
                if found:
                    m = found[0]
                    now = time.time()
                    segments = route_recorder.status().get("drive_segments", 0)
                    # 다른 마커면 바로 찍는다. 같은 마커는 그 사이에 로봇이 실제로
                    # 움직였을 때만 다시 찍는다. 가만히 마커를 보고 있는 동안
                    # 같은 지점이 수십 번 쌓이는 걸 막는다.
                    moved = segments != last_segments
                    if m["id"] != last_id or (moved and now - last_at > 5.0):
                        route_recorder.mark(m["id"], m["distance_cm"], m["angle_deg"])
                        print(f"[route] 자동 마크: ID {m['id']} · "
                              f"{m['distance_cm']:.1f}cm {m['angle_deg']:+.1f}도")
                        last_id, last_at, last_segments = m["id"], now, segments
            except Exception as e:
                print(f"[route] 자동 마크 실패(무시): {e}")
            stop_event.wait(0.6)

    def on_route(action, params):
        if action == "record/start":
            result = route_recorder.start(params.get("name", "route"))
            if marker_locator is not None:
                ev = threading.Event()
                auto_mark["stop"] = ev
                threading.Thread(target=_auto_mark_loop, args=(ev,), daemon=True).start()
                result["auto_mark"] = True
            return result

        if action == "record/stop":
            if auto_mark["stop"] is not None:
                auto_mark["stop"].set()
                auto_mark["stop"] = None
            route = route_recorder.stop()
            path = route_recorder.save(route)
            print(f"[route] 녹화 저장: {path} · 세그먼트 {len(route['segments'])}개")
            return {"saved": str(path), **route}

        if action == "record/status":
            return route_recorder.status()

        if action == "record/mark":
            # 지금 보이는 마커를 경로에 새긴다. 재생 때 이 지점에서 위치를 다시 잡는다.
            if marker_locator is None:
                return {"status": "unavailable", "reason": "마커 인식기가 없습니다."}
            found = marker_locator.find(hal.capture_frame())
            if not found:
                return {"status": "not_found", "reason": "지금 보이는 마커가 없습니다."}
            m = found[0]
            route_recorder.mark(m["id"], m["distance_cm"], m["angle_deg"])
            return {"status": "ok", "marker": m}

        if action == "list":
            return {"routes": list_routes()}

        if action == "play":
            name = params.get("name", "route")
            route = load_route(name)
            if route is None:
                return {"status": "not_found", "reason": f"경로 '{name}' 가 없습니다."}
            if route_player.status().get("playing"):
                return {"status": "busy", "reason": "이미 재생 중입니다."}
            # 재생은 오래 걸리므로 별도 스레드에서 돌리고 즉시 응답한다.
            def _play():
                with WheelLease("route"):
                    route_player.play(route)

            t = threading.Thread(target=_play, daemon=True)
            route_play_thread["t"] = t
            t.start()
            return {"status": "started", "name": name,
                    "segments": len(route.get("segments") or [])}

        if action == "stop":
            route_player.abort()
            return {"status": "aborting"}

        if action == "status":
            return {"player": route_player.status(), "recorder": route_recorder.status()}

        return {"status": "unknown_action", "action": action}

    stream_server.set_route_callback(on_route)

    # ---- 좌표 순찰 ----
    # 녹화를 되감는 대신 마커를 계속 보면서 그쪽으로 달린다. 오차가 쌓이지 않는
    # 유일한 방법이다(엔코더가 없으므로).
    odometry = Odometry(load_model())
    def on_patrol_finished():
        motion_owner["name"] = None

    def person_ahead():
        """앞에 사람이 있나. 순찰이 "기다릴지 돌아갈지"를 정할 때 쓴다.

        초음파는 앞을 막은 게 벽인지 사람인지 구분하지 못한다. 사람이면 돌아서
        지나가는 게 아니라 멈춰 서서 기다려야 하므로, AI 비전의 판단이 필요하다.
        0.75초보다 오래된 탐지는 안 믿는다 - 사람은 움직이고, 지나간 사람 때문에
        순찰이 멈춰 있으면 안 된다.
        """
        if ai_worker is None:
            return False
        latest = ai_worker.latest()
        return bool(
            latest
            and time.time() - latest.timestamp <= 0.75
            and any(item.class_name == "person" and item.confidence >= 0.45
                    for item in latest.detections)
        )

    marker_overlay["locator"] = marker_locator
    patrol = PatrolRunner(
        hal,
        marker_fn=(lambda: marker_locator.find(hal.capture_frame())) if marker_locator else None,
        speed_cap_fn=speed_cap_for_distance,
        odometry=odometry,
        on_finish=on_patrol_finished,
        person_fn=person_ahead,
    )

    def on_patrol(action, params):
        # 실물 로봇과 아이작 심은 서로 다른 공간이다. 웹이 어느 쪽인지 알려준다.
        env = params.get("env")
        if action == "start":
            if marker_locator is None:
                return {"error": "마커 인식이 꺼져 있다"}
            motion_owner["name"] = "patrol"
            return patrol.start(laps=int(params.get("laps", 1)), env=env,
                                keep_origin=params.get("keep_origin") == "1")
        if action == "stop":
            r = patrol.stop()
            motion_owner["name"] = None
            return r
        if action == "status":
            return patrol.status()
        if action == "map":
            return load_map(env)
        if action == "maps":
            return list_maps()
        if action == "shelves":
            return shelf_map.summary(load_map(env))
        if action == "assign_shelves":
            # 물품을 선반에 나눠 붙인다. 이미 배치된 물품은 그대로 두고 새 것만
            # 채운다 - 3등분 경계가 밀려서 멀쩡한 배치가 뒤집히면 안 된다.
            try:
                items = notify_supabase.fetch_items() or []
            except Exception as e:
                return {"error": f"물품 목록을 못 가져왔다: {e}"}
            ids = [int(i.get("id") or i.get("item_id")) for i in items
                   if (i.get("id") or i.get("item_id")) is not None]
            if not ids:
                return {"error": "물품이 하나도 없다"}
            codes = [s["code"] for s in shelf_map.shelves_from_map(load_map(env))]
            if not codes:
                return {"error": "순찰 지도에 선반으로 쓸 지점이 없다"}
            shelf_map.build_assignment(ids, codes)
            return shelf_map.summary(load_map(env))
        if action == "deliver":
            return driver["start"](int(params["item_id"]),
                                   from_home=params.get("from_home") != "0",
                                   return_after=params.get("return_after") != "0")
        if action == "avoid":
            # 장애물 비켜서기를 켜고 끈다. 기본은 꺼짐 - 좁은 방에서는 비켜설
            # 자리가 없어서 각도만 버린다.
            if "on" in params:
                patrol.avoid_enabled = params["on"] == "1"
            return {"avoid_enabled": patrol.avoid_enabled,
                    "안내": "켜면 막혔을 때 옆으로 비켜서고, 끄면 그 지점을 포기하고 다음으로 간다"}
        if action == "delivery_status":
            return dict(delivery)
        if action == "deliver_cancel":
            # 안내를 취소하면 로봇이 그 자리에서 멈추고 대기 자리로 돌아간다.
            # 창만 닫고 로봇을 그대로 두면, 사용자는 끝났다고 생각하는데 로봇은
            # 선반 앞에 서 있게 된다.
            if not delivery.get("running"):
                return {"error": "배달 중이 아니다"}
            delivery["cancel"] = True
            patrol.abort()          # 지금 가고 있던 주행을 즉시 멈춘다
            return {"status": "취소함 — 대기 자리로 돌아갑니다",
                    "phase": delivery.get("phase")}
        if action == "recall":
            # 기다리는 중이면 바로 복귀시킨다. 사람이 물건을 이미 가져갔는데
            # 남은 대기 시간을 다 채우고 있을 이유가 없다.
            if not delivery.get("running"):
                return {"error": "배달 중이 아니다"}
            delivery["recall"] = True
            return {"status": "복귀 지시함", "phase": delivery.get("phase")}
        if action == "dock":
            # 지금 어디에 있든 대기 자리(0,0)로 돌아간다.
            if delivery.get("running") or patrol.status().get("running"):
                return {"error": "다른 주행이 진행 중이다"}

            def _dock():
                with WheelLease("dock"):
                    patrol.goto(0, 0)
                    _dist, delta = odometry.vector_to(100.0, 0.0)
                    patrol.turn_in_place(delta)

            threading.Thread(target=_dock, daemon=True).start()
            return {"status": "복귀 중", "target": [0, 0]}
        if action == "pose":
            return odometry.pose()
        if action == "reset":
            # 지금 자리를 원점으로 삼는다. "여기가 0,0 이다".
            odometry.reset(float(params.get("x", 0)), float(params.get("y", 0)),
                           float(params.get("heading", 0)), note="사용자 지정")
            return odometry.pose()
        if action == "goto":
            with WheelLease("goto"):
                return patrol.goto(float(params["x"]), float(params["y"]))
        if action == "trim_from_offset":
            # 사람이 잰 값으로 직진 보정을 계산한다. 카메라 자동 측정은 좁은
            # 공간에서 분해능이 모자라(1.6초 주행 = 2픽셀) 못 믿는다.
            #
            # 로봇이 원호를 그린다고 보면 옆으로 벗어난 거리와 돌아간 각도는
            #     벗어난 거리 = 주행거리 x 각도(라디안) / 2
            # 이므로 각도 = 2 x 벗어난거리 / 주행거리. 이걸 초당으로 바꾸고
            # 회전 명령 1 단위가 내는 각속도로 나누면 필요한 trim 이 나온다.
            left = float(params.get("left_cm", 0))     # 왼쪽으로 벗어났으면 양수
            over = float(params.get("over_cm", 200))
            speed = float(params.get("speed", 65))
            if over <= 10:
                return {"error": "주행거리를 10cm 보다 크게 주세요"}
            rad = 2.0 * left / over
            seconds = odometry.seconds_for_cm(over, speed)
            drift_deg_per_s = math.degrees(rad) / seconds if seconds else 0.0
            turn_ref = float(sorted(odometry.model["turn_deg_per_s"])[0])
            deg_per_unit = (float(odometry.model["turn_deg_per_s"][str(int(turn_ref))])
                            / turn_ref)
            trim = float(odometry.model.get("drive_trim", 0.0)) +                 drift_deg_per_s / deg_per_unit
            trim = round(max(-25.0, min(25.0, trim)), 2)
            model = dict(odometry.model, drive_trim=trim)
            save_model(model, env)
            odometry.model = model
            patrol.odometry.model = model
            return {"drive_trim": trim,
                    "휜 각도": f"{math.degrees(rad):.1f}도 ({drift_deg_per_s:.2f} 도/s)",
                    "근거": f"{over:.0f}cm 가는 동안 왼쪽으로 {left:.0f}cm"}
        if action == "autotrim":
            # 로봇이 스스로 직진 정렬을 찾는다. 앞으로 2초 가면서 화면이 얼마나
            # 옆으로 흐르는지 재고, 그만큼을 회전으로 상쇄한 뒤 다시 잰다.
            if patrol.status().get("running"):
                return {"error": "순찰 중에는 정렬할 수 없다"}
            with WheelLease("autotrim"):
                r = calibrate_motion.autotrim(hal, odometry.model)
            # 자동으로 적용하지 않는다. 이 측정은 전진 시 화면 확대를 회전으로
            # 잘못 읽어서, 그대로 반영하면 오히려 나빠진다(위 autotrim 설명).
            r["applied"] = False
            r["안내"] = ("참고용이다. 이 값은 저장하지 않는다. 직진 휨은 "
                         "/patrol/testdrive?cm=190 후 줄자로 재서 "
                         "/patrol/trim_from_offset 으로 넣어야 정확하다")
            return r
        if action == "trim":
            # 직진 보정값. 왼쪽으로 휘면 양수를 키운다.
            model = dict(odometry.model)
            if "value" in params:
                model["drive_trim"] = float(params["value"])
                save_model(model, env)
                odometry.model = model
                patrol.odometry.model = model
            return {"drive_trim": model.get("drive_trim", 0.0),
                    "안내": "왼쪽으로 휘면 값을 키우고, 오른쪽으로 휘면 줄이세요"}
        if action == "testdrive":
            # 모델이 "이만큼"이라고 믿는 거리를 실제로 가고 멈춘다. 사람이 줄자로
            # 재서 scale 로 알려주면 표가 고쳐진다. 카메라·초음파로 자동 측정하는
            # 것보다 확실하다 - 무늬 없는 벽이나 먼 거리에서 자동 측정은 틀린다.
            cm = float(params.get("cm", 100))
            speed = float(params.get("speed", 65))
            seconds = odometry.seconds_for_cm(cm, speed)
            trim = float(params.get("trim", odometry.model.get("drive_trim", 0.0)))
            with WheelLease("testdrive"):
                hal.set_motion(speed, trim)
                time.sleep(seconds)
            return {"commanded_cm": cm, "speed": speed, "trim": trim,
                    "seconds": round(seconds, 2),
                    "안내": f"실제로 간 거리를 줄자로 재서 "
                            f"/patrol/scale?forward=<실제cm>&of={cm:.0f} 로 알려주세요"}
        if action == "testturn":
            deg = float(params.get("deg", 90))
            turn = float(params.get("turn", 60))
            seconds = odometry.seconds_for_deg(deg, turn)
            with WheelLease("testturn"):
                hal.set_motion(0, turn)
                time.sleep(seconds)
            return {"commanded_deg": deg, "turn": turn,
                    "seconds": round(seconds, 2),
                    "안내": f"실제로 돈 각도를 재서 "
                            f"/patrol/scale?turn=<실제도>&of={deg:.0f} 로 알려주세요"}
        if action == "scale":
            # 사람이 잰 실제값으로 표를 고친다. 실제/명령 비율만큼 곱한다.
            of = float(params.get("of", 100))
            model = dict(odometry.model)
            applied = {}
            if "forward" in params:
                k = float(params["forward"]) / of
                model["forward_cm_per_s"] = {a: round(b * k, 1)
                                             for a, b in model["forward_cm_per_s"].items()}
                applied["forward"] = round(k, 3)
            if "turn" in params:
                k = float(params["turn"]) / of
                model["turn_deg_per_s"] = {a: round(b * k, 1)
                                           for a, b in model["turn_deg_per_s"].items()}
                applied["turn"] = round(k, 3)
            model["scaled_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            model["scale_applied"] = applied
            save_model(model, env)
            odometry.model = model
            patrol.odometry.model = model
            return model
        if action == "refine":
            # 이미 있는 모델을 실제 주행 결과로 고친다. 짧은 측정의 5~8% 오차를
            # 한 번에 줄인다. 순찰이 거리를 넘치거나 모자라면 이걸 돌린다.
            if patrol.status().get("running"):
                return {"error": "순찰 중에는 보정할 수 없다"}
            with WheelLease("refine"):
                model = calibrate_motion.refine(
                    hal, odometry.model,
                    marker_fn=(lambda: marker_locator.find(hal.capture_frame()))
                    if marker_locator else None)
            save_model(model, env)
            odometry.model = model
            patrol.odometry.model = model
            return model
        if action == "calibrate":
            # 로봇이 스스로 "이 명령이 얼마나 움직이는지"를 잰다. 이 표가 없으면
            # 좌표 이동이 성립하지 않는다.
            if patrol.status().get("running"):
                return {"error": "순찰 중에는 측정할 수 없다"}
            with WheelLease("calibrate"):
                model = calibrate_motion.run(
                    hal,
                    marker_fn=(lambda: marker_locator.find(hal.capture_frame()))
                    if marker_locator else None)
            save_model(model, env)
            odometry.model = model
            patrol.odometry.model = model
            return model
        if action == "see":
            # 지금 보이는 마커. 지도를 만들 때 거리를 재는 용도.
            # pan 을 주면 카메라를 그쪽으로 돌린 뒤 본다.
            if marker_locator is None:
                return {"error": "마커 인식이 꺼져 있다"}
            if "pan" in params or "tilt" in params:
                hal.set_camera_angle(
                    pan=int(params["pan"]) if "pan" in params else None,
                    tilt=int(params["tilt"]) if "tilt" in params else None)
                time.sleep(1.0)
            found = marker_locator.find(hal.capture_frame())
            pan = float(getattr(hal, "cam_pan", 90.0))
            for m in found:
                # 로봇 몸통 기준 방향까지 같이 준다. 지도를 그릴 때 이게 필요하다.
                m["bearing_deg"] = round((pan - 90.0) + m["angle_deg"], 1)
            return {"markers": found, "cam_pan": pan}
        if action == "scan":
            # 카메라를 좌우·상하로 훑어 보이는 마커를 전부 모은다. 지도를 만들 때
            # "여기서 뭐가 보이나"를 한 번에 알아야 해서 서버에서 돈다. 왕복
            # HTTP 로 하면 서보가 매번 멈췄다 가서 훨씬 느리다.
            if marker_locator is None:
                return {"error": "마커 인식이 꺼져 있다"}
            tilts = [int(t) for t in params.get("tilts", "80,90,100").split(",")]
            pans = [int(x) for x in params.get("pans", "40,60,80,100,120,140").split(",")]
            best = {}
            for tilt in tilts:
                for pan in pans:
                    hal.set_camera_angle(pan=pan, tilt=tilt)
                    time.sleep(0.55)
                    for m in marker_locator.find(hal.capture_frame()):
                        # 같은 마커가 여러 각도에서 보이면 가장 크게(=정면에
                        # 가깝게) 보인 관측을 남긴다. 그게 가장 정확하다.
                        prev = best.get(m["id"])
                        if prev is None or m["px"] > prev["px"]:
                            best[m["id"]] = dict(m, cam_pan=pan, cam_tilt=tilt,
                                                 bearing_deg=round((pan - 90.0) + m["angle_deg"], 1))
            hal.set_camera_angle(pan=90, tilt=90)
            return {"found": sorted(best.values(), key=lambda m: m["id"]),
                    "scanned": {"tilts": tilts, "pans": pans}}

        raise ValueError(f"알 수 없는 순찰 명령: {action}")

    stream_server.set_patrol_callback(on_patrol)

    # ---- 발열 관리: 필요할 때만 빠르게 본다 ----
    # 가만히 있어도 CPU 130%, 60°C 였고 그중 대부분이 추론이었다. 아무도 안 보고
    # 아무 일도 없을 때까지 8fps 로 돌릴 이유가 없다.
    AI_FPS_ACTIVE = float(os.environ.get("LABKEEPER_AI_TARGET_FPS", "8"))
    AI_FPS_IDLE = float(os.environ.get("LABKEEPER_AI_IDLE_FPS", "3"))

    def _ai_speed_loop():
        """볼 사람이 있거나 로봇이 움직이면 빠르게, 아니면 느리게."""
        current = None
        while not shutdown_requested.is_set():
            try:
                busy = (
                    stream_server.ai_has_viewers()      # 웹에서 AI 화면을 보는 중
                    or stream_server.camera_has_viewers()
                    or patrol.status().get("running")   # 순찰 중
                    or delivery.get("running")          # 배달 중
                    or motion_owner["name"] is not None
                )
                want = AI_FPS_ACTIVE if busy else AI_FPS_IDLE
                if want != current and ai_worker is not None:
                    ai_worker.set_target_fps(want)
                    current = want
                    print(f"[labkeeper] AI 추론 {want:.0f}fps "
                          f"({'활성' if busy else '대기'})")
            except Exception as e:
                print(f"[labkeeper] AI 속도 조절 실패(무시): {e}")
            shutdown_requested.wait(3.0)

    if ai_worker is not None:
        threading.Thread(target=_ai_speed_loop, name="ai-speed", daemon=True).start()

    # ---- 대여 배달 ----
    # 웹에서 대여를 걸면 로봇이 그 물품의 선반 앞으로 간다. mission_engine 은
    # "무엇을 가지러 가는가"를 기록할 뿐 운전은 하지 않으므로, 실제 주행은
    # 여기서 좌표 순찰의 goto 를 빌려 쓴다.
    #
    # 배경 스레드로 도는 이유는 주행이 수십 초 걸리기 때문이다. HTTP 요청을
    # 붙잡고 있으면 웹이 그동안 아무 것도 못 하고, 진행 상황도 볼 수 없다.
    # 물품 앞에 서 있어 주는 시간. 사람이 와서 물건을 집어갈 틈이다. 이 동안
    # 로봇은 멈춰 있고, 지나면 대기 자리로 돌아간다.
    DELIVERY_DWELL_S = float(os.environ.get("LABKEEPER_DELIVERY_DWELL_S", "25"))

    def _deliver(item_id, from_home, return_after=True):
        """선반 좌표까지 갔다가 대기 자리로 돌아온다.

        이동은 전적으로 좌표로 한다. QR 은 이동에 쓰지 않는다 - QR 은 어느 물품인지
        알려주는 재고용 값이지 위치를 알려주지 않는다. 게다가 QR 값은 관리자만
        읽을 수 있는 별도 테이블(item_qr_codes)에 있어서 로봇은 갖고 있지도 않다.
        로봇은 읽은 문자열을 그대로 올리고, 어느 물품인지는 서버가 판단한다.
        """
        pmap = load_map()
        shelf = shelf_map.locate(item_id, pmap)
        delivery.update(running=True, item_id=item_id, shelf=shelf,
                        phase="navigating", qr=None, error_cm=None, message="")
        try:
            if from_home:
                # 로봇이 대기 자리에 있다는 뜻. 거기가 (0,0) 이다.
                odometry.reset(0, 0, 0, note="배달 출발")

            with WheelLease("deliver"):
                r = patrol.goto(shelf["x_cm"], shelf["y_cm"])

                # 가는 도중에 취소됐으면 남은 일을 건너뛰고 곧장 돌아간다.
                # patrol 의 중단 신호를 여기서 풀어줘야 복귀 주행이 돈다 -
                # 안 풀면 복귀 goto 도 즉시 중단돼 로봇이 선반 앞에 남는다.
                if delivery.get("cancel"):
                    patrol.clear_abort()
                    delivery.update(phase="cancelled", message="안내 취소됨")
                    self_return = True
                else:
                    self_return = False

                blocked = bool(r.get("blocked")) and not delivery.get("cancel")
                delivery.update(phase="blocked" if blocked else "arrived",
                                error_cm=r["error_cm"],
                                message="막혀서 못 감" if blocked else "도착")
                event_queue.push("delivery_arrived", {
                    "item_id": item_id, "shelf_code": shelf["code"],
                    "x_cm": r["pose"]["x_cm"], "y_cm": r["pose"]["y_cm"],
                    "error_cm": r["error_cm"], "blocked": blocked,
                })

                if not blocked and not self_return:
                    # 재고 확인용 QR 스캔. 이동과는 무관하고 실패해도 넘어간다.
                    # 여기 물품이 실제로 있는지를 기록으로 남기는 것이 목적이다.
                    try:
                        code = hal.scan_qr_now()
                        delivery.update(qr=code)
                        if code:
                            event_queue.push("audit_scan", {
                                "location": code, "at_item_id": item_id,
                                "shelf_code": shelf["code"],
                            })
                    except Exception as scan_error:
                        print(f"[deliver] 재고 스캔 실패(무시): {scan_error}")

                    # 사람이 물건을 집어갈 시간을 준다. recall 이 오면 바로 끝낸다.
                    delivery.update(phase="waiting")
                    waited = 0.0
                    while (waited < DELIVERY_DWELL_S
                           and not delivery.get("recall")
                           and not delivery.get("cancel")):
                        time.sleep(0.5)
                        waited += 0.5
                    if delivery.get("cancel"):
                        patrol.clear_abort()
                        delivery.update(phase="cancelled", message="안내 취소됨")

                if return_after:
                    delivery.update(phase="returning", message="대기 자리로 복귀")
                    back = patrol.goto(0, 0)
                    # 방향까지 처음처럼 돌려놔야 다음 배달이 같은 조건에서 시작한다.
                    _dist, delta = odometry.vector_to(100.0, 0.0)
                    patrol.turn_in_place(delta)
                    delivery.update(error_cm=back["error_cm"])
                    event_queue.push("delivery_returned", {
                        "item_id": item_id,
                        "x_cm": back["pose"]["x_cm"], "y_cm": back["pose"]["y_cm"],
                        "error_cm": back["error_cm"],
                    })
                    if not blocked:
                        delivery.update(phase="docked", message="복귀 완료")

            delivery.update(running=False, recall=False, cancel=False)
        except Exception as e:
            delivery.update(running=False, phase="error", message=str(e))
            print(f"[deliver] 실패: {e}")

    def start_delivery(item_id, from_home=True, return_after=True):
        """배달을 시작한다. 곧바로 돌아오고 실제 주행은 배경에서 돈다."""
        if delivery["running"]:
            return {"error": f"이미 물품 {delivery['item_id']} 배달 중"}
        if patrol.status().get("running"):
            return {"error": "순찰 중이다. 먼저 순찰을 멈춰라"}
        shelf = shelf_map.locate(item_id, load_map())
        if not shelf:
            return {"error": f"물품 {item_id} 의 선반이 정해져 있지 않다. "
                             f"/patrol/assign_shelves 를 먼저 부르세요"}
        delivery["recall"] = False
        delivery["cancel"] = False
        threading.Thread(target=_deliver, args=(item_id, from_home, return_after),
                         daemon=True).start()
        return {"status": "navigating", "item_id": item_id, "shelf": shelf}

    driver["start"] = start_delivery

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
                if motion_owner["name"]:
                    pass          # 자율 주행이 바퀴를 잡고 있다 — 건드리지 않는다
                elif stale:
                    hal.stop()  # 3초 동안 웹에서 조이스틱 신호가 없으면 자동 정지
                elif cur_speed > 0 and distance < OBSTACLE_STOP_DISTANCE:
                    hal.stop()  # 전진할 때만 막는다 — 후진 탈출은 허용
                else:
                    hal.set_motion(cur_speed, cur_turn)
                    # 손으로 몬 것도 좌표에 반영한다. 이걸 빼먹으면 WASD 로
                    # 옮겨놓고 "대기 자리로" 를 눌렀을 때 로봇이 자기가 아직
                    # (0,0) 에 있다고 믿어서 꿈쩍도 안 한다.
                    odometry.apply(cur_speed, cur_turn, TICK_SECONDS)
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
