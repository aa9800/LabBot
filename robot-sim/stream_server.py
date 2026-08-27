"""초경량 로컬 MJPEG 카메라 스트리밍 서버 (Raspberry Pi 5 / 로컬 고속 직결용).

웹 브라우저(관리자 Robot Console)가 <img src="http://로봇IP:8080/stream">으로 직접 접근하면
Supabase DB나 스토리지를 거치지 않고 30 FPS / ~30ms급 초고속 실시간 영상을 바로 전송한다.
외부 웹서버 의존성 없이 순수 파이썬 표준 라이브러리(http.server, threading, socket)만 사용한다.
"""
import io
import json
import logging
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
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        try:
            self._handle_get()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception as e:
            logger.debug(f"HTTP GET handler exception: {e}")

    def _handle_get(self):
        req_path = self.path.split("?")[0]
        if req_path == "/stream":
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            client_version = 0
            try:
                while True:
                    frame, client_version = _buffer.wait_for_new_frame(client_version, timeout=0.5)
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
        elif req_path.startswith("/snapshot"):
            frame = _buffer.get_latest()
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
            applied = {"pan": pan, "tilt": tilt}
            if _camera_angle_callback is not None:
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
                res = {"status": "ok", "found": True, "code": code, "timestamp": time.time()}
            else:
                res = {"status": "ok", "found": False, "message": "QR 코드가 감지되지 않았습니다. 카메라 각도를 맞춰주세요."}
            self.wfile.write(json.dumps(res).encode("utf-8"))
        elif req_path.startswith("/buzzer"):
            # 웹 버튼 클릭 시 로봇 능동 부저 즉각 작동
            if _buzzer_callback is not None:
                try:
                    _buzzer_callback()
                except Exception as e:
                    logger.warn(f"Buzzer callback failed: {e}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "부저 경보가 작동했습니다."}).encode("utf-8"))
        elif req_path.startswith("/siren"):
            # 웹 버튼 클릭 시 로봇 RGB LED 경광등 즉각 점멸
            if _siren_callback is not None:
                try:
                    _siren_callback()
                except Exception as e:
                    logger.warn(f"Siren callback failed: {e}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "경광등이 점멸합니다."}).encode("utf-8"))
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
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "error", "message": message}).encode("utf-8"))


_camera_angle_callback = None
_drive_callback = None
_telemetry_provider = None
_qr_scan_callback = None
_buzzer_callback = None
_siren_callback = None


def set_buzzer_callback(cb):
    """부저 작동 콜백 등록."""
    global _buzzer_callback
    _buzzer_callback = cb


def set_siren_callback(cb):
    """경광등 작동 콜백 등록."""
    global _siren_callback
    _siren_callback = cb


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


def set_camera_frame(jpeg_bytes: bytes):
    """카메라 루프에서 새 프레임이 인코딩될 때마다 호출하여 버퍼를 갱신하고 클라이언트를 깨운다."""
    _buffer.update(jpeg_bytes)


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
                    "LabKeeper Live",
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
