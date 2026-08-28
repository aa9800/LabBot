"""LabKeeper 실시간 AI 비전 가드 & 방범 관제 스트리밍 서버 (Port 8081).
로봇 FPV 카메라 영상을 실시간으로 분석하여 AI 객체 탐지 바운딩 박스를 오버레이하고
방범 침입자 추적, 부저/경광등 연동, 안전 규정 위반 자동 판정을 수행합니다.
"""
import os
import sys
import time
import json
import threading
import urllib.request
from urllib.parse import parse_qs, urlparse
import cv2
import numpy as np
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai_vision.detector import LabPatrolDetector
from ai_vision.safety_engine import LabSafetyEngine
from ai_vision.intruder_tracker import IntruderTracker
from notify_supabase import report_safety_event

ROBOT_IP = "127.0.0.1"

def update_robot_urls(ip: str):
    global ROBOT_IP
    ROBOT_IP = ip

# Supabase에서 최신 로봇 IP 주기적 조회 (디지털 트윈/실물 자동 전환)
def _poll_robot_ip():
    from notify_supabase import fetch_robot_local_ip
    while _running:
        try:
            # 같은 PC에서 Isaac이 실행 중이면 가상 로봇을 우선한다. 그렇지 않을 때만
            # Supabase에 보고된 실물 Raspbot IP로 전환한다.
            try:
                urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=0.4).read()
                if ROBOT_IP != "127.0.0.1":
                    update_robot_urls("127.0.0.1")
                time.sleep(2)
                continue
            except Exception:
                pass
            ip = (fetch_robot_local_ip() or "").strip()
            if ip and ip != ROBOT_IP:
                print(f"[AI Stream Server] 로봇 IP 갱신됨: {ip}")
                update_robot_urls(ip)
        except Exception:
            pass
        time.sleep(5)

AI_STREAM_PORT = 8081

_latest_annotated_jpeg = None
_lock = threading.Lock()
_running = True
_active_alerts = []
_current_detections = []
_intruder_guard_mode = False
_buzzer_active = False
_siren_active = False
_last_guard_action = "대기 중"
_last_checkout_alert_at = 0.0


def _expected_vision_class(item_name: str):
    """DB 물품명을 현재 학습된 YOLO 클래스에 연결한다."""
    name = (item_name or "").lower()
    rules = (
        (("현미경", "microscope"), "microscope"),
        (("원심분리", "centrifuge"), "centrifuge"),
        (("피펫", "pipette"), "pipette"),
        (("비커", "beaker"), "beaker"),
        (("플라스크", "flask"), "flask"),
        (("시약", "에탄올", "reagent", "buffer"), "reagent_bottle"),
        (("소화기", "extinguisher"), "fire_extinguisher"),
        (("스필", "spill kit"), "spill_kit"),
        (("인화성", "flammable"), "flammable_cabinet"),
        (("유해폐기물", "biohazard"), "biohazard_bin"),
    )
    for keywords, class_name in rules:
        if any(keyword in name for keyword in keywords):
            return class_name
    return None


def _checkout_verdict(expected_name: str):
    expected_class = _expected_vision_class(expected_name)
    with _lock:
        detections = list(_current_detections)
    centered = [
        d for d in detections
        if d.get("type") in ("ASSET", "SAFETY")
        and d.get("centered")
        and float(d.get("confidence", 0)) >= 50.0
    ]
    detected_classes = sorted({d.get("class_name") for d in centered if d.get("class_name")})
    detected_items = sorted({d.get("name_kr") for d in centered if d.get("name_kr")})
    if not expected_class:
        return {
            "status": "ok", "verdict": "unsupported", "expected_name": expected_name,
            "detected_items": detected_items,
            "reason": "현재 AI 학습 클래스에 없는 품목이므로 QR 검증만 적용됩니다.",
        }
    extras = [name for name in detected_classes if name != expected_class]
    if extras:
        return {
            "status": "ok", "verdict": "blocked", "expected_name": expected_name,
            "expected_class": expected_class, "detected_items": detected_items,
            "reason": "예약 물품 외 추가 물품 또는 다른 물품이 카메라 중앙에서 감지되었습니다.",
        }
    if expected_class in detected_classes:
        return {
            "status": "ok", "verdict": "verified", "expected_name": expected_name,
            "expected_class": expected_class, "detected_items": detected_items,
            "reason": "QR 대상과 AI 인식 물품이 일치합니다.",
        }
    return {
        "status": "ok", "verdict": "inconclusive", "expected_name": expected_name,
        "expected_class": expected_class, "detected_items": detected_items,
        "reason": "물품을 카메라 중앙에서 충분히 확인하지 못했습니다. QR 검증은 계속 적용됩니다.",
    }


class AIStreamHandler(BaseHTTPRequestHandler):
    """AI 비전 스트리밍 & 상호작용 HTTP 핸들러."""

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        global _latest_annotated_jpeg, _intruder_guard_mode, _buzzer_active, _siren_active, _last_checkout_alert_at
        req_path = self.path.split("?")[0]
        try:
            self._handle_get(req_path)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # 클라이언트가 연결을 끊었을 뿐 — 서버는 계속 동작
        except Exception:
            pass

    def _handle_get(self, req_path):
        global _latest_annotated_jpeg, _intruder_guard_mode, _buzzer_active, _siren_active, _last_checkout_alert_at

        if req_path in ("/ai_stream", "/stream"):
            self.send_response(200)
            self.send_header(
                "Content-Type", "multipart/x-mixed-replace; boundary=frame"
            )
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            while _running:
                with _lock:
                    frame_bytes = _latest_annotated_jpeg

                if frame_bytes is not None:
                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(frame_bytes)
                        self.wfile.write(b"\r\n")
                    except Exception:
                        break
                time.sleep(0.04)  # ~25 FPS

        elif req_path in ("/ai_snapshot", "/snapshot"):
            with _lock:
                frame_bytes = _latest_annotated_jpeg

            if frame_bytes is not None:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(frame_bytes)
            else:
                self.send_response(503)
                self.end_headers()

        elif req_path == "/ai_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with _lock:
                status_payload = {
                    "status": "ok",
                    "intruder_guard_mode": _intruder_guard_mode,
                    "buzzer_active": _buzzer_active,
                    "siren_active": _siren_active,
                    "guard_action": _last_guard_action,
                    "detections": _current_detections,
                    "active_alerts": [a["text"] for a in _active_alerts],
                    "timestamp": time.time(),
                }
            self.wfile.write(json.dumps(status_payload).encode("utf-8"))

        elif req_path == "/checkout/verify":
            params = parse_qs(urlparse(self.path).query)
            expected_name = params.get("expected_name", [""])[0].strip()
            result = _checkout_verdict(expected_name)
            if result["verdict"] == "blocked" and time.time() - _last_checkout_alert_at > 3.0:
                _last_checkout_alert_at = time.time()
                _buzzer_active = True
                threading.Thread(target=self._auto_off_buzzer, daemon=True).start()
                snapshot = _latest_annotated_jpeg
                threading.Thread(
                    target=report_safety_event,
                    kwargs={
                        "rule_id": "CHECKOUT_ITEM_MISMATCH",
                        "severity": "HIGH",
                        "note": f"AI 대여 확인 보류: 예약 [{expected_name}], 감지 {result.get('detected_items', [])}",
                        "source": "ai-checkout-guard",
                        "snapshot_bytes": snapshot,
                    },
                    daemon=True,
                ).start()
                try:
                    urllib.request.urlopen(f"http://{ROBOT_IP}:8080/buzzer", timeout=0.3)
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))

        elif req_path == "/toggle_guard":
            _intruder_guard_mode = not _intruder_guard_mode
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "intruder_guard_mode": _intruder_guard_mode}).encode("utf-8"))

        elif req_path == "/trigger_buzzer":
            _buzzer_active = True
            threading.Thread(target=self._auto_off_buzzer, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "🔊 원격 부저 경보가 2초간 작동합니다."}).encode("utf-8"))

        elif req_path == "/trigger_siren":
            _siren_active = True
            threading.Thread(target=self._auto_off_siren, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "🚨 RGB 경찰차 경광등이 3초간 점멸합니다."}).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def _auto_off_buzzer(self):
        global _buzzer_active
        time.sleep(2.0)
        _buzzer_active = False

    def _auto_off_siren(self):
        global _siren_active
        time.sleep(3.0)
        _siren_active = False

    def log_message(self, format, *args):
        pass


def _ai_processing_loop(detector: LabPatrolDetector, safety_engine: LabSafetyEngine, tracker: IntruderTracker):
    """로봇 FPV 스냅샷을 지속적으로 가져와 AI 추론, 침입자 추적, 안전 규정 평가 수행.

    ★ MOG2 배경 차분 전처리: 움직임이 없는 프레임에서는 무거운 YOLO를 건너뛴다.
       움직임 감지 시에만 YOLO를 실행하여 연산량을 약 70% 절약.
    ★ 초음파 침입 트리거: 정지 상태에서 거리값이 크게 변하면 "뭔가 지나갔다"로 판단.
    """
    global _latest_annotated_jpeg, _running, _active_alerts, _current_detections, _last_guard_action, _buzzer_active, _siren_active
    print("[AI Stream Server] AI Vision & Guard Loop Started (MOG2 + 초음파 트리거 활성).")

    last_error_log = 0.0

    # ── MOG2 배경 차분기 초기화 ──
    bg_subtractor = cv2.createBackgroundSubtractorMOG2(
        history=300,           # 배경 모델에 300프레임 기억
        varThreshold=40,       # 감도 (낮을수록 민감)
        detectShadows=False,   # 그림자 무시 — 속도 우선
    )
    MOTION_THRESHOLD = 800     # 움직이는 픽셀 수가 이 이상이면 "움직임 있음"
    frames_since_last_yolo = 0
    FORCE_YOLO_INTERVAL = 30   # 움직임 없어도 30프레임(~1초)마다 1회는 YOLO 실행

    # 마지막 YOLO 탐지 결과 (움직임 없을 때 유지용)
    last_detections = []
    last_annotated = None

    # ── 초음파 침입 트리거 상태 ──
    sonar_baseline = None       # 정지 시 측정한 기준 거리 (cm)
    sonar_baseline_samples = []  # 기준값 계산용 샘플 (5개 평균)
    SONAR_TRIGGER_DELTA = 30.0   # 기준 대비 ±30cm 이상 변하면 트리거
    sonar_last_trigger_time = 0.0
    SONAR_COOLDOWN = 5.0         # 초음파 트리거 쿨다운 (5초)

    while _running:
        try:
            # 1. 텔레메트리 (거리 센서, 구역 위치) 조회
            obstacle_dist = 999.0
            current_zone = "연구실 복도"
            try:
                t_req = urllib.request.Request(f"http://{ROBOT_IP}:8080/telemetry", headers={"User-Agent": "LabKeeper-AI"})
                with urllib.request.urlopen(t_req, timeout=0.3) as t_resp:
                    t_data = json.loads(t_resp.read().decode("utf-8"))
                    obstacle_dist = float(t_data.get("obstacle_cm", t_data.get("distance_cm", 999.0)))
                    current_zone = str(t_data.get("zone", "연구실 복도"))
            except Exception:
                pass

            # ── 초음파 침입 트리거 (방범 모드에서만) ──
            if _intruder_guard_mode and obstacle_dist < 900:
                now = time.time()
                if sonar_baseline is None:
                    # 기준값 수집 중 (처음 5개 샘플 평균)
                    sonar_baseline_samples.append(obstacle_dist)
                    if len(sonar_baseline_samples) >= 5:
                        sonar_baseline = sum(sonar_baseline_samples) / len(sonar_baseline_samples)
                        print(f"[AI Stream Server] 초음파 기준 거리 설정: {sonar_baseline:.1f}cm")
                else:
                    delta = abs(obstacle_dist - sonar_baseline)
                    if delta > SONAR_TRIGGER_DELTA and now - sonar_last_trigger_time > SONAR_COOLDOWN:
                        sonar_last_trigger_time = now
                        print(f"[AI Stream Server] ⚡ 초음파 침입 트리거! 기준={sonar_baseline:.0f}cm → 현재={obstacle_dist:.0f}cm (차이={delta:.0f}cm)")
                        _active_alerts.append({"time": now, "text": f"⚡ 초음파 침입 감지: {obstacle_dist:.0f}cm (기준 {sonar_baseline:.0f}cm)"})
                        # 부저 경보 (로봇에 직접)
                        try:
                            urllib.request.urlopen(f"http://{ROBOT_IP}:8080/buzzer", timeout=0.3)
                        except Exception:
                            pass
            elif not _intruder_guard_mode:
                # 방범 모드 꺼지면 기준값 리셋
                sonar_baseline = None
                sonar_baseline_samples.clear()

            # 2. 로봇 카메라 스냅샷 조회
            req = urllib.request.Request(
                f"http://{ROBOT_IP}:8080/snapshot", headers={"User-Agent": "LabKeeper-AI"}
            )
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                raw_img = np.asarray(bytearray(resp.read()), dtype=np.uint8)
                frame = cv2.imdecode(raw_img, cv2.IMREAD_COLOR)

            if frame is not None and frame.size > 0:
                frames_since_last_yolo += 1

                # ── MOG2 배경 차분: 움직임 감지 ──
                fg_mask = bg_subtractor.apply(frame)
                motion_pixels = cv2.countNonZero(fg_mask)
                has_motion = motion_pixels > MOTION_THRESHOLD
                force_yolo = frames_since_last_yolo >= FORCE_YOLO_INTERVAL

                # 3. AI 객체 탐지 — 움직임이 있거나 강제 주기일 때만 실행
                if has_motion or force_yolo:
                    detections = detector.detect(frame)
                    frames_since_last_yolo = 0
                    last_detections = detections

                    with _lock:
                        _current_detections = [
                            {
                                "class_name": d["class_name"],
                                "name_kr": d["name_kr"],
                                "confidence": round(d["confidence"] * 100, 1),
                                "type": d["type"],
                                "box": d["box"],
                                "centered": (
                                    frame.shape[1] * 0.25 <= (d["box"][0] + d["box"][2]) / 2 <= frame.shape[1] * 0.75
                                    and frame.shape[0] * 0.18 <= (d["box"][1] + d["box"][3]) / 2 <= frame.shape[0] * 0.88
                                ),
                            }
                            for d in detections
                        ]
                else:
                    # 움직임 없음 → 이전 탐지 결과 유지, YOLO 스킵
                    detections = last_detections

                # 4. 방범 침입자 추적 모드 활성화 시 처리
                person_box = None
                for d in detections:
                    if d.get("class_name") in ("person", "human", "intruder"):
                        person_box = d["box"]
                        break

                if _intruder_guard_mode:
                    track_cmd = tracker.compute_tracking_command(person_box, obstacle_dist)
                    _last_guard_action = track_cmd["action"]
                    if track_cmd["detected"]:
                        _buzzer_active = True
                        _siren_active = True
                        
                        # 하드웨어 알람 스팸 방지 (3초 쿨다운)
                        now = time.time()
                        if not hasattr(tracker, "last_alarm_time") or now - tracker.last_alarm_time > 3.0:
                            tracker.last_alarm_time = now
                            
                            # 침입자 발견 시 Supabase 긴급 경보
                            _, snap_bytes = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                            report_safety_event(
                                rule_id="INTRUDER_DETECTED",
                                severity="CRITICAL",
                                note=f"🚨 [방범경보] 구역 [{current_zone}]에서 비인가 침입자가 감지되어 로봇이 추적 및 경보를 발동했습니다!",
                                source="guard-robot",
                                snapshot_bytes=snap_bytes.tobytes(),
                            )
                            _active_alerts.append({"time": time.time(), "text": "🚨 [방범] 침입자 발견! 부저 작동 및 자동 추적 중"})
    
                            # 부저/사이렌 물리적 발동
                            try:
                                urllib.request.urlopen(f"http://{ROBOT_IP}:8080/buzzer", timeout=0.3)
                            except Exception:
                                pass

                        # 로봇 모터 제어 명령 (지속 전송)
                        try:
                            urllib.request.urlopen(f"http://{ROBOT_IP}:8080/drive?mode=manual&speed={track_cmd['speed']}&turn={track_cmd['turn']}", timeout=0.3)
                        except Exception:
                            pass
                else:
                    _last_guard_action = "방범 모드 OFF"

                # 5. 실시간 연구실 안전 & 시설 규정 평가 (움직임 있을 때만)
                if has_motion or force_yolo:
                    safety_events = safety_engine.evaluate_frame_safety(
                        current_zone=current_zone,
                        detections=detections,
                        obstacle_dist_cm=obstacle_dist,
                    )

                    # 6. 안전 위반 발생 시 Supabase DB 로깅
                    for ev in safety_events:
                        _, snap_bytes = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        report_safety_event(
                            rule_id=ev["rule_code"],
                            severity=ev["severity"],
                            note=f"{ev['title']} - {ev['description']}",
                            source="ai-vision-guard",
                            snapshot_bytes=snap_bytes.tobytes(),
                        )
                        _active_alerts.append({"time": time.time(), "text": ev["title"]})

                # 오래된 알림 정리 (4초 경과)
                _active_alerts = [a for a in _active_alerts if time.time() - a["time"] < 4.0]

                # 7. 바운딩 박스 및 사이버틱 HUD 렌더링
                annotated = detector.draw_detections(frame, detections)

                # MOG2 상태 HUD — 움직임 감지 상태 표시
                motion_label = f"MOTION: {motion_pixels}px" if has_motion else "STATIC"
                motion_color = (0, 200, 255) if has_motion else (100, 100, 100)
                cv2.putText(annotated, motion_label, (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.38, motion_color, 1, cv2.LINE_AA)

                # 8. 방범 상태 & 부저/경광등 HUD 오버레이
                h, w = annotated.shape[:2]
                if _intruder_guard_mode:
                    badge_color = (0, 0, 240) if person_box else (0, 165, 255)
                    cv2.rectangle(annotated, (w - 150, 8), (w - 8, 30), badge_color, -1)
                    cv2.putText(annotated, "GUARD MODE ON", (w - 142, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

                if _buzzer_active:
                    cv2.rectangle(annotated, (w - 150, 36), (w - 8, 56), (0, 0, 255), -1)
                    cv2.putText(annotated, "BUZZER ALARM!", (w - 142, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)

                if _active_alerts:
                    latest_alert = _active_alerts[-1]["text"]
                    cv2.rectangle(annotated, (0, h - 28), (w, h), (20, 20, 220), -1)
                    cv2.putText(annotated, latest_alert, (10, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)

                # 9. JPEG 인코딩
                _, jpeg = cv2.imencode(
                    ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                )
                with _lock:
                    _latest_annotated_jpeg = jpeg.tobytes()

        except Exception as exc:
            now = time.time()
            if now - last_error_log > 5.0:
                print(f"[AI Stream Server] processing loop error: {type(exc).__name__}: {exc}")
                last_error_log = now
            time.sleep(0.08)

        time.sleep(0.03)


def start_ai_stream_server():
    """AI 스트림 서버 시작."""
    detector = LabPatrolDetector()
    safety_engine = LabSafetyEngine()
    tracker = IntruderTracker()

    t = threading.Thread(
        target=_ai_processing_loop, args=(detector, safety_engine, tracker), daemon=True
    )
    t.start()

    ip_thread = threading.Thread(target=_poll_robot_ip, daemon=True)
    ip_thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", AI_STREAM_PORT), AIStreamHandler)
    server.daemon_threads = True
    print(
        f"[AI Stream Server] Serving AI Vision Stream on http://localhost:{AI_STREAM_PORT}/ai_stream"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[AI Stream Server] Stopping...")
        server.server_close()


if __name__ == "__main__":
    start_ai_stream_server()
