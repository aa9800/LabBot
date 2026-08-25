"""반복 가능한 스모크 테스트 — pygame 판단 로직 + Supabase 연동 어댑터가
네트워크나 robot-sim/.env 없이도 죽지 않고 안전하게 동작하는지 확인한다.

Webots 쪽(3D 렌더링, 실제 장애물 정지, Safety 이벤트가 웹에 실제로 뜨는지)은
GUI 프로그램이라 여기서 자동화할 수 없다 — 아래 WEBOTS_MANUAL_CHECKLIST를
사람이 Webots에서 직접 확인해야 한다.

실행: python smoke_test.py
컨트롤러 로직이나 notify_supabase.py를 고칠 때마다 먼저 이걸로 빠르게 확인하고,
Webots 체크리스트로 눈으로 재확인하는 순서를 추천한다.
"""
import sys

import notify_supabase as ns
from controller import PatrolController
from sim.engine import World
from sim.hal_sim import SimHAL

# Windows 콘솔(cp949 등)에서 이 파일의 한글 특수문자(—)가 UnicodeEncodeError를 내는 걸
# 막는다 — 실제 로직과는 무관한, 터미널 출력 인코딩 문제일 뿐이다.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

STEP_DT = 1 / 60

# 웹 연동 없이도 체크포인트 로직을 검증하기 위한 오프라인 고정값.
FAKE_ITEMS = [
    {"id": 1, "name": "니퍼", "location": "A-1"},
    {"id": 2, "name": "드라이버 세트", "location": "A-1"},
]

WEBOTS_MANUAL_CHECKLIST = """
Webots 수동 체크리스트 (사람이 직접 확인 — 자동화 불가)
  1. Webots에서 robot-sim/webots_project/worlds/lab.wbt를 열고 ▶(재생)을 누른다.
  2. 왼쪽 Scene Tree에 "OBSTACLE_1"이 보이는지 확인한다.
     (없으면 lab_baseline.wbt를 lab.wbt로 복사해 복원 — robot-sim/README.md 참고)
  3. 로봇이 OBSTACLE_1에 가까워지면 스스로 멈추는지 확인한다.
  4. Console 패널에 "장애물 감지(...cm) — 정지 + SR-01 안전이벤트 전송"이 뜨는지 확인한다.
  5. 웹 admin.html에 로그인 후 "안전 이벤트" 탭에 새 NEEDS_REVIEW 이벤트가 실제로
     뜨는지 확인한다 (robot-sim/.env에 Supabase 접속정보가 있어야 이 5번까지 확인 가능).
"""


def check_patrol_logic():
    """pygame 판단 로직이 장애물을 만나면 멈추고, 치우면 다시 순찰을 재개하는지
    (창 없이) 확인한다."""
    world = World(items=FAKE_ITEMS)
    hal = SimHAL(world)
    events = []
    controller = PatrolController(
        hal,
        on_scan=lambda qr: events.append(("scan", qr)),
        on_obstacle=lambda d: events.append(("obstacle", d)),
        on_obstacle_cleared=lambda: events.append(("cleared", None)),
    )
    for i in range(1200):
        if i == 200:
            world.add_obstacle_ahead()
        if i == 500:
            world.clear_obstacles()
        controller.tick(STEP_DT)
        world.robot.step(STEP_DT)

    assert any(e[0] == "obstacle" for e in events), "장애물 감지 콜백이 한 번도 안 불림"
    assert any(e[0] == "cleared" for e in events), "장애물 해제 콜백이 한 번도 안 불림"
    print("[OK] pygame 판단 로직 — 장애물 감지/해제 정상 동작")


def check_supabase_adapter_offline_safe():
    """네트워크가 안 되는 상황을 강제로 흉내내서, notify_supabase의 각 함수가 예외를
    던지지 않고 안전한 기본값을 돌려주는지 확인한다.

    주의: 이 로컬 개발 환경의 robot-sim/.env에는 실제 프로덕션 Supabase 접속정보가 들어있다
    (is_configured() == True). 그래서 여기서 실제로 report_safety_event()를 호출하면
    프로덕션 safety_events 테이블에 진짜 이벤트가 들어가 버린다 — 실제로 처음 이 테스트를
    만들 때 이 실수를 했다가 발견해서(id=2, note="smoke test") 지웠다. 그 사고를 다시
    반복하지 않도록, urlopen을 일부러 실패하게 바꿔치기해서 "네트워크가 없을 때" 경로만
    검증하고, 실제 네트워크 호출은 절대 하지 않는다.
    """
    original_urlopen = ns.urllib.request.urlopen

    def _always_fail(*args, **kwargs):
        raise OSError("smoke_test: 의도적으로 네트워크 실패를 흉내냄 (실제 호출 아님)")

    ns.urllib.request.urlopen = _always_fail
    try:
        items = ns.fetch_items()
        assert isinstance(items, list) and items == [], "네트워크 실패 시 fetch_items()는 빈 리스트여야 함"

        command = ns.fetch_robot_command()
        assert command == {"mode": "auto", "speed": 0.0, "turn": 0.0}, (
            "네트워크 실패 시 fetch_robot_command()는 안전하게 자동/정지 기본값을 줘야 함"
        )

        ok = ns.report_safety_event("SR-01", severity="LOW", note="smoke test", source="smoke-test")
        assert ok is False, "네트워크 실패 시 report_safety_event()는 False를 돌려줘야 함"
    finally:
        ns.urllib.request.urlopen = original_urlopen  # 실제 네트워크 함수 원상복구

    print(
        "[OK] notify_supabase 어댑터 — 네트워크 실패 시에도 안 죽고 안전한 기본값 반환 "
        f"(이 머신의 .env 설정 여부: configured={ns.is_configured()}, 실제 네트워크 호출은 안 함)"
    )


def main():
    check_patrol_logic()
    check_supabase_adapter_offline_safe()
    print(WEBOTS_MANUAL_CHECKLIST)
    print("스모크 테스트 통과 — Webots 부분은 위 체크리스트로 사람이 직접 확인할 것")


if __name__ == "__main__":
    main()
