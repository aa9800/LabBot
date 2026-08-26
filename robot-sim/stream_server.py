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

    def wait_for_new_frame(self, last_version: int, timeout: float = 1.0):
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
        # Nagle 알고리즘 비활성화 — 프레임 패킷을 모으지 않고 즉시 송출(전송 지연 수백ms 제거)
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def do_OPTIONS(self):
        # CORS 프리플라이트 요청 허용 (Private Network Access 포함)
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        if self.path == "/stream":
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
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                logger.debug(f"Stream client disconnected: {e}")
        elif self.path == "/snapshot":
            frame = _buffer.get_latest()
            if frame:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_error(404, "No frame available")
        elif self.path.startswith("/camera"):
            # 초저지연 로컬 카메라 서보 각도 조절 직결 엔드포인트
            import urllib.parse
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            pan = int(qs["pan"][0]) if "pan" in qs else None
            tilt = int(qs["tilt"][0]) if "tilt" in qs else None
            if _camera_angle_callback is not None:
                try:
                    _camera_angle_callback(pan, tilt)
                except Exception as e:
                    logger.warn(f"Camera angle callback failed: {e}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path.startswith("/drive"):
            # 초저지연 로컬 조이스틱 주행 직결 엔드포인트 (0ms 반응)
            import urllib.parse
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            mode = qs.get("mode", ["manual"])[0]
            speed = float(qs["speed"][0]) if "speed" in qs else 0.0
            turn = float(qs["turn"][0]) if "turn" in qs else 0.0
            if _drive_callback is not None:
                try:
                    _drive_callback(mode, speed, turn)
                except Exception as e:
                    logger.warn(f"Drive callback failed: {e}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path == "/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            data = _telemetry_provider() if _telemetry_provider is not None else {}
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.path in ("/health", "/status"):
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


_camera_angle_callback = None
_drive_callback = None
_telemetry_provider = None


def set_camera_angle_callback(cb):
    """서보 각도 변경 콜백 등록 (RealHAL.set_camera_angle 연동)."""
    global _camera_angle_callback
    _camera_angle_callback = cb


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