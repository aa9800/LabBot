"""PC에서 실행하는 Supabase 중계 서버.

로봇이 자체 핫스팟 모드(인터넷 없음)일 때도 Supabase에 데이터를 주고받을 수 있게,
로봇의 요청을 이 PC가 대신 진짜 Supabase로 전달해준다. PC가 이더넷 등으로 이미
인터넷이 있고, 동시에 로봇 핫스팟에도 Wi-Fi로 붙어있어서 가능한 방식이다
(2026-08-26, 사용자 제안: "로컬에서 데이터 거쳐서 넘기면 안되나?").

사용법:
  1. 이 PC에서 실행: python supabase_relay.py
  2. 로봇의 ~/labkeeper/.env에서 SUPABASE_URL을 이 PC의 "로봇 핫스팟 쪽" IP로 바꾼다
     예) SUPABASE_URL=http://10.42.0.43:8899
     (SUPABASE_SECRET_KEY는 그대로 둔다 — 이 서버가 헤더를 그대로 전달한다)
  3. notify_supabase.py / real_hal.py / run_real.py는 전혀 안 고쳐도 된다 —
     요청이 이 중계 서버를 한 번 거쳐서 나갈 뿐, URL 경로/방식은 실제 Supabase REST API와
     완전히 동일하다(그냥 문자 그대로 전달만 한다).

주의: apikey/Authorization 헤더(secret key)를 그대로 전달하므로, 이 중계 서버는
로봇 핫스팟처럼 신뢰할 수 있는 로컬망에서만 켜둔다 — 외부(공인 인터넷)에 노출하지 않는다.
표준 라이브러리만 쓴다(notify_supabase.py와 같은 이유 — 새 의존성 추가 안 함).
"""
import http.server
import urllib.error
import urllib.request

TARGET = "https://mblvvolsgzjzctfxvbwg.supabase.co"
LISTEN_PORT = 8899


class RelayHandler(http.server.BaseHTTPRequestHandler):
    def _relay(self, method):
        target_url = TARGET + self.path
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(content_length) if content_length else None

        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length")
        }

        req = urllib.request.Request(target_url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except (urllib.error.URLError, OSError) as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"relay error: {e}".encode("utf-8"))

    def do_GET(self):
        self._relay("GET")

    def do_POST(self):
        self._relay("POST")

    def do_PATCH(self):
        self._relay("PATCH")

    def do_PUT(self):
        self._relay("PUT")

    def do_DELETE(self):
        self._relay("DELETE")

    def log_message(self, format, *args):  # noqa: A002
        print(f"[relay] {self.address_string()} {format % args}")


def main():
    server = http.server.ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), RelayHandler)
    print(f"[relay] listening on 0.0.0.0:{LISTEN_PORT} -> {TARGET}")
    print("[relay] Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[relay] stopping")
        server.shutdown()


if __name__ == "__main__":
    main()
