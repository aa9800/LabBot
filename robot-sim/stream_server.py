"""초경량 로컬 MJPEG 카메라 스트리밍 서버 (Raspberry Pi 5 / 로컬 고속 직결용).

웹 브라우저(관리자 Robot Console)가 <img src="http://로봇IP:8080/stream">으로 직접 접근하면
Supabase DB나 스토리지를 거치지 않고 30 FPS / ~30ms급 초고속 실시간 영상을 바로 전송한다.
외부 웹서버 의존성 없이 순수 파이썬 표준 라이브러리(http.server, threading, socket)만 사용한다.
"""
import io
import json
import logging
import os
import shutil
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import event_queue

logger = logging.getLogger("stream_server")


class FrameBuffer:
    """새 프레임이 인코딩될 때마다 대기 중인 모든 스트리밍 클라이언트에 즉시 통지하는 버퍼."""

    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()
        self.version = 0
        self.last_updated = 0.0
        self.fps_counter = 0
        self.fps_last_time = time.time()
        self.current_fps = 0.0
        # 지금 이 스트림을 실제로 받아가는 클라이언트 수. 0이면 프레임을 만들어봐야
        # 버리는 것이라 생산 측(카메라 루프 · AI 루프)이 인코딩을 건너뛴다.
        self.viewers = 0
        self._viewer_lock = threading.Lock()

    def add_viewer(self):
        with self._viewer_lock:
            self.viewers += 1

    def remove_viewer(self):
        with self._viewer_lock:
            self.viewers = max(0, self.viewers - 1)

    def has_viewers(self):
        return self.viewers > 0

    def update(self, frame_bytes: bytes):
        with self.condition:
            self.frame = frame_bytes
            self.version += 1
            now = time.time()
            self.last_updated = now
            self.fps_counter += 1
            if now - self.fps_last_time >= 1.0:
                self.current_fps = self.fps_counter / (now - self.fps_last_time)
                self.fps_counter = 0
                self.fps_last_time = now
            self.condition.notify_all()

    def get_latest(self):
        with self.condition:
            return self.frame

    def wait_for_new_frame(self, last_version: int, timeout: float = 0.5):
        """새 프레임이 들어올 때까지 대기(0ms 지연)하다가 최신 프레임과 버전을 반환."""
        with self.condition:
            if self.version == last_version:
                self.condition.wait(timeout)
            return self.frame, self.version


_buffer = FrameBuffer()
_ai_buffer = FrameBuffer()
_lab_preview_buffer = FrameBuffer()


class StreamingHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 스트리밍 도중 매 프레임 콘솔 로그 도배 방지
        pass

    def setup(self):
        super().setup()
        # Nagle 알고리즘 비활성화 및 송신 버퍼 16KB 제한 — 프레임 지연 누적(Bufferbloat) 원천 차단
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16384)
        except OSError:
            pass

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        # CORS 프리플라이트 요청 허용 (Private Network Access 포함)
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_POST(self):
        try:
            req_path = self.path.split("?")[0]
            if req_path != "/config/item-locations":
                self.send_error(404, "Not Found")
                return
            if _item_locations_update_callback is None:
                self._send_json_error(501, "물품 위치 캐시 동기화를 지원하지 않습니다.")
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 512 * 1024:
                self._send_json_error(413, "물품 위치 데이터 크기가 올바르지 않습니다.")
                return
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            result = _item_locations_update_callback(payload)
            self._send_json(200, {"status": "ok", **(result or {})})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send_json_error(400, str(exc))
        except Exception as exc:
            self._send_json_error(500, f"물품 위치 캐시 갱신 실패: {exc}")

    def do_GET(self):
        try:
            self._handle_get()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception as e:
            logger.debug(f"HTTP GET handler exception: {e}")

    def _handle_get(self):
        req_path = self.path.split("?")[0]
        if req_path in ("/stream", "/ai/stream", "/lab_preview"):
            selected_buffer = (
                _ai_buffer if req_path == "/ai/stream"
                else _lab_preview_buffer if req_path == "/lab_preview"
                else _buffer
            )
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            client_version = 0
            selected_buffer.add_viewer()
            try:
                while True:
                    frame, client_version = selected_buffer.wait_for_new_frame(client_version, timeout=0.5)
                    if frame:
                        chunk = (
                            b"--FRAME\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
                            + frame + b"\r\n"
                        )
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                selected_buffer.remove_viewer()
        elif req_path.startswith("/snapshot") or req_path == "/ai/snapshot":
            frame = (_ai_buffer if req_path == "/ai/snapshot" else _buffer).get_latest()
            if frame:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_error(404, "No frame available")
        elif req_path.startswith("/camera"):
            # 초저지연 로컬 카메라 서보 각도 조절 직결 엔드포인트
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            pan = int(qs["pan"][0]) if "pan" in qs else None
            tilt = int(qs["tilt"][0]) if "tilt" in qs else None
            # pan_dir/tilt_dir 은 "그 방향으로 계속 움직여라"(-1/0/+1)다. 화살표를
            # 누르고 있는 동안 쓰며, 로봇이 매 틱 목표를 밀어줘서 끊기지 않는다.
            pan_dir = int(qs["pan_dir"][0]) if "pan_dir" in qs else None
            tilt_dir = int(qs["tilt_dir"][0]) if "tilt_dir" in qs else None
            applied = {"pan": pan, "tilt": tilt}
            if (pan_dir is not None or tilt_dir is not None) and _camera_direction_callback is not None:
                try:
                    result = _camera_direction_callback(pan_dir, tilt_dir)
                    if isinstance(result, dict):
                        applied.update(result)
                except Exception as e:
                    self._send_json_error(500, f"Camera direction callback failed: {e}")
                    return
            elif _camera_angle_callback is not None:
                try:
                    callback_result = _camera_angle_callback(pan, tilt)
                    if isinstance(callback_result, dict):
                        applied.update(callback_result)
                except Exception as e:
                    self._send_json_error(500, f"Camera angle callback failed: {e}")
                    return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "applied": applied}).encode("utf-8"))
        elif req_path.startswith("/drive"):
            # 두 곳에서 동시에 조작하면 서로 다른 속도가 번갈아 나가 모터가
            # 세게/약하게를 반복한다. 약한 모터는 아예 못 일어나고 소리만 낸다.
            # 실제로 관리자 페이지를 두 탭에서 연 채로 "오른쪽 바퀴가 안 돈다"를
            # 한참 뒤쫓았다. 화면 두 개를 켜둔 걸 사람이 알아채기 어려우므로
            # 로봇이 알려준다.
            _note_drive_client(self.client_address[0] if self.client_address else "?")
            # 초저지연 로컬 조이스틱 주행 직결 엔드포인트 (0ms 반응)
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            mode = qs.get("mode", ["manual"])[0]
            speed = float(qs["speed"][0]) if "speed" in qs else 0.0
            turn = float(qs["turn"][0]) if "turn" in qs else 0.0
            applied = {"mode": mode, "speed": speed, "turn": turn}
            if _drive_callback is not None:
                try:
                    callback_result = _drive_callback(mode, speed, turn)
                    if isinstance(callback_result, dict):
                        applied.update(callback_result)
                except Exception as e:
                    self._send_json_error(500, f"Drive callback failed: {e}")
                    return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "applied": applied}).encode("utf-8"))
        elif req_path == "/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            data = _telemetry_provider() if _telemetry_provider is not None else {}
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif req_path.startswith("/patrol/"):
            if _patrol_callback is None:
                self._send_json(503, {"error": "순찰 기능이 꺼져 있다"})
                return
            action = req_path[len("/patrol/"):].strip("/")
            qs = parse_qs(urlparse(self.path).query)
            params = {k: v[0] for k, v in qs.items()}
            try:
                self._send_json(200, _patrol_callback(action, params) or {})
            except Exception as e:
                self._send_json(400, {"error": str(e)})

        elif req_path.startswith("/route/"):
            # 경로 녹화·재생. 좌표 순찰의 2단계다 — 사람이 한 번 몰아 보여준 것을
            # 그대로 따라 하게 하고, 마커로 위치를 다시 잡아 오차 누적을 막는다.
            if _route_callback is None:
                self._send_json(200, {"status": "unavailable",
                                      "reason": "경로 실행기가 등록되지 않았습니다."})
                return
            action = req_path[len("/route/"):].strip("/")
            qs = parse_qs(urlparse(self.path).query)
            params = {k: v[0] for k, v in qs.items()}
            try:
                self._send_json(200, _route_callback(action, params) or {})
            except Exception as e:
                self._send_json_error(500, f"Route action failed: {e}")
        elif req_path == "/health":
            # 라즈베리파이 하드웨어 상태(온도·스로틀·CPU·메모리). 관리자 페이지에서
            # 상시 표시한다 — 2026-08-30에 82.9도까지 올라 스로틀링이 걸린 채로
            # 서보 명령이 밀리는 문제가 있었고, 그게 화면에 안 보여서 늦게 찾았다.
            self._send_json(200, read_pi_health())
        elif req_path == "/ai/status":
            data = _ai_status_provider() if _ai_status_provider is not None else {
                "running": False,
                "mode": "unavailable",
                "error": "AI 추론 엔진이 등록되지 않았습니다.",
            }
            self._send_json(200, data)
        elif req_path == "/checkout/verify":
            if _checkout_verify_callback is None:
                self._send_json(200, {"verdict": "unavailable", "reason": "AI 검증 엔진 미등록"})
                return
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            params = {key: values[0] for key, values in qs.items()}
            self._send_json(200, _checkout_verify_callback(params))
        elif req_path == "/config/item-locations/status":
            result = _item_locations_status_callback() if _item_locations_status_callback else {
                "status": "unsupported"
            }
            self._send_json(200, result)
        elif req_path == "/guard/status":
            result = _guard_status_callback() if _guard_status_callback else {"status": "unsupported"}
            self._send_json(200, result)
        elif req_path == "/guard/config":
            if _guard_config_callback is None:
                self._send_json_error(501, "야간 경비 설정을 지원하지 않습니다.")
                return
            parsed = urlparse(self.path)
            raw = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            values = {}
            for key, value in raw.items():
                if key in {"enabled", "force_night"}:
                    values[key] = str(value).lower() in {"1", "true", "yes", "on"}
                elif key in {"start_hour", "end_hour"}:
                    values[key] = int(value)
                elif key == "patrol_interval_minutes":
                    values[key] = float(value)
            self._send_json(200, _guard_config_callback(**values))
        elif req_path == "/guard/trigger":
            if _guard_trigger_callback is None:
                self._send_json_error(501, "야간 경비 트리거를 지원하지 않습니다.")
                return
            parsed = urlparse(self.path)
            raw = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            result = _guard_trigger_callback(
                raw.get("source", "web"),
                str(raw.get("person", "0")).lower() in {"1", "true", "yes", "on"},
            )
            self._send_json(200, result)
        elif req_path.startswith("/scan_qr"):
            # 웹 버튼 클릭 시 온디맨드 1회 QR 스캔 실행
            code = None
            if _qr_scan_callback is not None:
                try:
                    code = _qr_scan_callback()
                except Exception as e:
                    logger.warn(f"QR scan callback failed: {e}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            if code:
                res = {"status": "ok", "found": True, "timestamp": time.time()}
                if isinstance(code, dict):
                    res.update(code)
                else:
                    res["code"] = code
            else:
                res = {"status": "ok", "found": False, "message": "QR 코드가 감지되지 않았습니다. 카메라 각도를 맞춰주세요."}
            self.wfile.write(json.dumps(res).encode("utf-8"))
        elif req_path == "/guide/start":
            if _guide_start_callback is None:
                self._send_json_error(501, "이 로봇은 물품 안내를 지원하지 않습니다.")
                return
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            params = {key: values[0] for key, values in qs.items()}
            try:
                result = _guide_start_callback(params)
                self._send_json(200, {"status": "ok", **(result or {})})
            except (ValueError, KeyError) as e:
                self._send_json_error(404, str(e))
            except Exception as e:
                self._send_json_error(500, f"안내 시작 실패: {e}")
        elif req_path == "/guide/status":
            result = _guide_status_callback() if _guide_status_callback is not None else {"status": "unsupported"}
            self._send_json(200, result)
        elif req_path in ("/guide/complete", "/guide/cancel"):
            if _guide_finish_callback is None:
                self._send_json_error(501, "이 로봇은 물품 안내를 지원하지 않습니다.")
                return
            result = _guide_finish_callback("completed" if req_path.endswith("complete") else "cancelled")
            self._send_json(200, {"status": "ok", **(result or {})})
        elif req_path.startswith("/buzzer"):
            # 웹 버튼 클릭 시 경보 부저 작동.
            # 콜백이 없거나 실패하면 정직하게 실패를 돌려준다 — 예전에는 무조건
            # "부저 경보가 작동했습니다"를 반환해서, Ctrl_Buzzer가 존재하지도 않던
            # 시절에도 웹에 초록 성공 토스트가 떴다.
            if _buzzer_callback is None:
                self._send_json_error(501, "이 로봇에는 부저가 연결되어 있지 않습니다.")
                return
            try:
                result = _buzzer_callback()
            except Exception as e:
                self._send_json_error(500, f"부저 작동 실패: {e}")
                return
            if isinstance(result, dict) and result.get("status") == "error":
                self._send_json_error(500, result.get("message", "부저 작동 실패"))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            body = {"status": "ok", "message": "부저 경보가 울렸습니다."}
            if isinstance(result, dict):
                body.update(result)
            self.wfile.write(json.dumps(body).encode("utf-8"))
        elif req_path == "/events":
            # PC의 relay.py가 주기적으로 긁어가는 이벤트 큐 — 로봇은 인터넷이 없어서
            # Supabase를 직접 못 부르므로, 여기 쌓아두면 인터넷 되는 PC가 대신 써준다.
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            after = int(qs["after"][0]) if "after" in qs else 0
            limit = int(qs["limit"][0]) if "limit" in qs else 100
            body = {"events": event_queue.drain_after(after, limit), **event_queue.stats()}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))
        elif req_path == "/events/snapshot":
            # 안전 이벤트에 묶인 증거 사진 — seq로 조회한다.
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            seq = int(qs["seq"][0]) if "seq" in qs else -1
            blob = event_queue.get_snapshot(seq)
            if blob:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()
                self.wfile.write(blob)
            else:
                self.send_error(404, "No snapshot for that seq")
        elif req_path in ("/health", "/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            status_data = {
                "status": "ok",
                "streaming": True,
                "fps": round(_buffer.current_fps, 1),
                "has_frame": _buffer.frame is not None,
                "last_updated": round(_buffer.last_updated, 2),
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def _send_json_error(self, status_code, message):
        self._send_json(status_code, {"status": "error", "message": message})

    def _send_json(self, status_code, body):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))


_camera_angle_callback = None
_camera_direction_callback = None
# 최근에 주행 명령을 보낸 곳들. 둘 이상이면 경고한다.
_drive_clients = {}
_drive_conflict_warned_at = [0.0]


def _note_drive_client(ip):
    now = time.time()
    _drive_clients[ip] = now
    for old_ip, seen in list(_drive_clients.items()):
        if now - seen > 5.0:
            del _drive_clients[old_ip]
    if len(_drive_clients) > 1 and now - _drive_conflict_warned_at[0] > 10.0:
        _drive_conflict_warned_at[0] = now
        print(f"[stream_server] 주행 명령이 {len(_drive_clients)}곳에서 오고 있습니다: "
              f"{', '.join(sorted(_drive_clients))} — 화면을 하나만 열어두세요. "
              f"서로 다른 속도가 번갈아 나가면 모터가 제대로 돌지 않습니다.")


_route_callback = None
_patrol_callback = None
_drive_callback = None
_telemetry_provider = None
_qr_scan_callback = None
_buzzer_callback = None
_guide_start_callback = None
_guide_status_callback = None
_guide_finish_callback = None
_ai_status_provider = None
_checkout_verify_callback = None
_item_locations_update_callback = None
_item_locations_status_callback = None
_guard_status_callback = None
_guard_config_callback = None
_guard_trigger_callback = None


def set_buzzer_callback(cb):
    """부저 작동 콜백 등록."""
    global _buzzer_callback
    _buzzer_callback = cb


# 경광등(set_siren_callback)은 제거했다 — 이 보드의 LED는 표시등 수준이라
# 실내 경보로 인식이 안 된다는 실기기 확인 결과(2026-08-27). 경보는 부저로만 한다.


# 라즈베리파이 스로틀 비트 (vcgencmd get_throttled 반환값)
THROTTLE_BITS = {
    0: ("under_voltage", "저전압"),
    1: ("freq_capped", "주파수 제한"),
    2: ("throttled", "스로틀링"),
    3: ("soft_temp_limit", "온도 제한"),
}


def _read_first_line(path):
    try:
        with open(path, "r") as f:
            return f.readline().strip()
    except Exception:
        return None


def read_pi_health():
    """온도·스로틀·CPU·메모리를 sysfs에서 읽는다.

    vcgencmd를 부르면 프로세스를 띄우느라 수십 ms가 든다. 이 엔드포인트는 웹이
    주기적으로 부르므로 커널이 이미 노출한 파일만 읽어 비용을 거의 0으로 둔다.
    """
    health = {"ok": True}

    # 온도 (millidegree C)
    raw = _read_first_line("/sys/class/thermal/thermal_zone0/temp")
    health["temp_c"] = round(int(raw) / 1000.0, 1) if raw and raw.isdigit() else None

    # 스로틀 상태 비트맵
    raw = _read_first_line("/sys/devices/platform/soc/soc:firmware/get_throttled")
    flags, active = None, []
    if raw:
        try:
            flags = int(raw, 16) if raw.startswith("0x") else int(raw)
        except ValueError:
            flags = None
    if flags is not None:
        for bit, (key, label) in THROTTLE_BITS.items():
            if flags & (1 << bit):
                active.append({"key": key, "label": label})
    health["throttle_flags"] = flags
    health["throttled_now"] = active          # 지금 걸려 있는 것만. 이력 비트(16~19)는 뺀다.

    # 배터리 상태 — 전압을 직접 읽는 게 아니라 저전압 플래그로 유추한다.
    #
    # 이 확장보드(YB_Pcb_Car, I2C 0x16)는 배터리 전압을 알려주지 않는다.
    # 라이브러리에 함수가 없고, 레지스터 0x00~0x5F 어디에도 전압으로 읽히는
    # 값이 없다(probe_battery.py 로 확인, 2026-08-31). 그래서 퍼센트는 못 낸다.
    #
    # 대신 라즈베리파이가 자기 전원이 처질 때 세우는 저전압 비트를 쓴다.
    # 배터리가 닳으면 모터가 돌 때 전압이 먼저 주저앉고, 그때 이 비트가 뜬다.
    # 정확한 잔량은 아니지만 "곧 꺼진다"는 신호로는 실제로 맞는다.
    #
    #   bit 0  지금 저전압    -> 위험. 주행 중이면 곧 멈춘다
    #   bit 16 부팅 후 겪음   -> 주의. 부하가 걸릴 때 처지고 있다
    if flags is None:
        health["power"] = {"state": "unknown", "label": "알 수 없음",
                           "how": "스로틀 플래그를 못 읽음"}
    elif flags & (1 << 0):
        health["power"] = {"state": "critical", "label": "저전압 — 충전 필요",
                           "how": "라즈베리파이 저전압 플래그(지금)"}
    elif flags & (1 << 16):
        health["power"] = {"state": "weak", "label": "전압 처짐 이력 있음",
                           "how": "라즈베리파이 저전압 플래그(부팅 후)"}
    else:
        health["power"] = {"state": "ok", "label": "정상",
                           "how": "라즈베리파이 저전압 플래그 없음"}
    health["power"]["note"] = "확장보드가 전압을 알려주지 않아 잔량(%)은 표시할 수 없다"

    # CPU 클럭 (kHz -> MHz)
    raw = _read_first_line("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    health["cpu_mhz"] = round(int(raw) / 1000.0) if raw and raw.isdigit() else None

    # 로드 애버리지 -> 코어 수로 나눠 백분율
    try:
        load1 = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        health["load_pct"] = round(load1 / cores * 100)
    except Exception:
        health["load_pct"] = None

    # 메모리 (MemAvailable 기준 사용률)
    total = avail = None
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
                if total is not None and avail is not None:
                    break
    except Exception:
        pass
    if total:
        health["mem_used_pct"] = round((total - (avail or 0)) / total * 100)
        health["mem_total_mb"] = round(total / 1024)
    else:
        health["mem_used_pct"] = None
        health["mem_total_mb"] = None

    # 가동 시간
    raw = _read_first_line("/proc/uptime")
    try:
        health["uptime_sec"] = int(float(raw.split()[0])) if raw else None
    except Exception:
        health["uptime_sec"] = None

    # 무선 신호. iw 를 부르면 프로세스를 띄우니 커널이 이미 내놓은 파일을 읽는다.
    # 로봇이 돌아다니는 물건이라 신호가 떨어지면 명령도 영상도 같이 끊긴다.
    health["wifi_dbm"] = None
    health["wifi_quality"] = None
    try:
        with open("/proc/net/wireless", "r") as f:
            for line in f:
                if "wlan0" not in line:
                    continue
                cols = line.split()
                # 값 끝에 점이 붙어 나온다: "52." "-58."
                health["wifi_quality"] = float(cols[2].rstrip("."))
                health["wifi_dbm"] = float(cols[3].rstrip("."))
                break
    except Exception:
        pass

    # 디스크. 이벤트 큐와 주행 로그가 여기 쌓이므로 가득 차면 안전이벤트가 유실된다.
    try:
        usage = shutil.disk_usage("/")
        health["disk_used_pct"] = round(usage.used / usage.total * 100)
        health["disk_free_gb"] = round(usage.free / 1e9, 1)
    except Exception:
        health["disk_used_pct"] = None
        health["disk_free_gb"] = None

    # AI 가 조용히 죽으면 경비 로봇이 아무것도 못 보는데 알 방법이 없다.
    health["ai_ok"] = None
    health["ai_fps"] = None
    health["ai_error"] = None
    if _ai_status_provider is not None:
        try:
            ai = _ai_status_provider() or {}
            health["ai_ok"] = bool(ai.get("running")) and not ai.get("error")
            health["ai_fps"] = ai.get("actual_fps")
            health["ai_error"] = ai.get("error")
        except Exception as e:
            health["ai_ok"] = False
            health["ai_error"] = f"{type(e).__name__}: {e}"

    return health


def set_patrol_callback(cb):
    """좌표 순찰 명령을 받을 함수. (action, params) -> dict."""
    global _patrol_callback
    _patrol_callback = cb


def set_route_callback(cb):
    """경로 녹화·재생 콜백. cb(action, params) -> dict."""
    global _route_callback
    _route_callback = cb


def set_camera_direction_callback(cb):
    """방향 이동 콜백 등록 (RealHAL.set_camera_direction 연동)."""
    global _camera_direction_callback
    _camera_direction_callback = cb


def set_camera_angle_callback(cb):
    """서보 각도 변경 콜백 등록 (RealHAL.set_camera_angle 연동)."""
    global _camera_angle_callback
    _camera_angle_callback = cb


def set_qr_scan_callback(cb):
    """온디맨드 QR 스캔 콜백 등록."""
    global _qr_scan_callback
    _qr_scan_callback = cb


set_scan_qr_callback = set_qr_scan_callback


def set_drive_callback(cb):
    """직결 주행 명령 콜백 등록 (run_real 연동)."""
    global _drive_callback
    _drive_callback = cb


def set_telemetry_provider(fn):
    """실시간 텔레메트리 제공 함수 등록 (거리, 모드, 서보 각도 등)."""
    global _telemetry_provider
    _telemetry_provider = fn


def set_ai_status_provider(fn):
    """라즈봇 로컬 AI 엔진 상태 제공 함수를 등록한다."""
    global _ai_status_provider
    _ai_status_provider = fn


def set_checkout_verify_callback(fn):
    """로봇 내부 최신 AI 결과로 대여 물품 구성을 확인하는 콜백."""
    global _checkout_verify_callback
    _checkout_verify_callback = fn


def set_item_location_callbacks(update=None, status=None):
    """PC relay가 DB 위치 정보를 로봇의 로컬 캐시에 동기화하는 콜백."""
    global _item_locations_update_callback, _item_locations_status_callback
    _item_locations_update_callback = update
    _item_locations_status_callback = status


def set_guard_callbacks(status=None, configure=None, trigger=None):
    """주야간 경비 상태기계의 조회·설정·테스트 트리거를 등록한다."""
    global _guard_status_callback, _guard_config_callback, _guard_trigger_callback
    _guard_status_callback = status
    _guard_config_callback = configure
    _guard_trigger_callback = trigger


def set_guide_callbacks(start=None, status=None, finish=None):
    """물품 안내 시작/상태/종료 콜백을 등록한다."""
    global _guide_start_callback, _guide_status_callback, _guide_finish_callback
    _guide_start_callback = start
    _guide_status_callback = status
    _guide_finish_callback = finish


def camera_has_viewers():
    """일반 카메라 스트림(/stream)을 지금 보고 있는 사람이 있는가."""
    return _buffer.has_viewers()


def ai_has_viewers():
    """AI 오버레이 스트림(/ai/stream)을 지금 보고 있는 사람이 있는가."""
    return _ai_buffer.has_viewers()


def set_camera_frame(jpeg_bytes: bytes):
    """카메라 루프에서 새 프레임이 인코딩될 때마다 호출하여 버퍼를 갱신하고 클라이언트를 깨운다."""
    _buffer.update(jpeg_bytes)


def set_ai_frame(jpeg_bytes: bytes):
    """객체 박스가 그려진 AI 프리뷰를 원본 스트림과 별도 버퍼에 보관한다."""
    _ai_buffer.update(jpeg_bytes)


def set_lab_preview_frame(jpeg_bytes: bytes):
    """Isaac 실험실 고정 카메라 프레임을 로봇 FPV와 분리된 버퍼에 저장한다."""
    _lab_preview_buffer.update(jpeg_bytes)


def get_latest_frame() -> bytes:
    """메모리에 저장된 가장 최근 JPEG 바이트를 가져온다 (스토리지 업로드 / 스냅샷용)."""
    return _buffer.get_latest()


def start_stream_server(host="0.0.0.0", port=8080, daemon=True) -> ThreadingHTTPServer:
    """백그라운드 스레드에서 초경량 HTTP MJPEG 스트리밍 서버를 시작한다."""
    server = ThreadingHTTPServer((host, port), StreamingHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=daemon)
    thread.start()
    print(f"[stream_server] MJPEG 실시간 스트림 서버 시작됨: http://{host}:{port}/stream")
    return server


if __name__ == "__main__":
    # 단독 테스트 실행 시 (가상 테스트 프레임 생성)
    import cv2
    import numpy as np

    print("MJPEG 스트리밍 서버 단독 테스트 모드 (포트 8080)")
    start_stream_server(port=8080)

    cap = cv2.VideoCapture(0)
    try:
        while True:
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    _, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                    set_camera_frame(jpeg.tobytes())
            else:
                img = np.zeros((240, 320, 3), dtype=np.uint8)
                img[:] = (25, 30, 38)
                cv2.putText(
                    img,
                    "LabBot Live",
                    (40, 90),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (255, 180, 50),
                    2,
                )
                cv2.putText(
                    img,
                    time.strftime("%H:%M:%S"),
                    (70, 150),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.2,
                    (50, 220, 100),
                    2,
                )
                _, jpeg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                set_camera_frame(jpeg.tobytes())
            time.sleep(0.033)
    except KeyboardInterrupt:
        print("서버 종료")
        if cap.isOpened():
            cap.release()
