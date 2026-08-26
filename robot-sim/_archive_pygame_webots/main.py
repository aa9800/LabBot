"""가상 로봇 순찰 연습 — 실제 Raspbot이 오기 전에 라인트래킹/장애물회피/QR스캔/실사를 미리 연습한다.

시작할 때 LabKeeper 웹의 Supabase DB(items 테이블)에 등록된 실제 물품 목록을 가져와서
위치(location)별로 가상 선반(체크포인트)을 자동으로 만든다. 웹에 물품을 더 등록하면
다음 실행부터 그대로 반영된다 — 이 파일에 가짜 데이터를 넣을 필요가 없다.

(예전에는 로컬 FastAPI 서버(labkeeper-web-local, 127.0.0.1:8000)를 봤지만, 그 로컬웹은
더 이상 쓰지 않기로 해서 Webots와 동일하게 notify_supabase.py로 통일했다 — 실제 서비스
웹(Supabase 기반)에 직접 붙는다.)

실행: python main.py  (robot-sim/.env에 Supabase 접속정보를 채워두는 걸 추천 —
없으면 체크포인트 없이 라인트래킹/장애물 로직만 연습하는 모드로 동작한다. robot-sim/.env.example 참고)

조작:
  SPACE  로봇 진행 방향 앞에 장애물 놓기 (초음파 회피 → Safety 이벤트 전송)
  C      장애물 전체 치우기
  R      로봇 위치 리셋
  M      무작위로 물품 하나를 선반에서 몰래 없앰 (실사 불일치 시나리오 연습)
  F      지금까지 스캔한 결과와 전체 물품을 비교해 불일치를 계산 (로컬 계산 —
         아직 audit_sessions DB에는 기록되지 않음, 실제 DB 연동은 다음 단계 예정)
  N      스캔 기록 초기화 (새 실사 다시 시작)
  ESC    종료
"""
import sys

import pygame

from controller import PatrolController
from notify_supabase import fetch_items, is_configured, report_safety_event
from sim.engine import HEIGHT, WIDTH, World, draw
from sim.hal_sim import SimHAL


def _on_obstacle(world, distance):
    world.note(f"장애물 감지({distance}px) — 정지, Safety 이벤트 전송")
    report_safety_event(
        rule_id="SR-01",
        severity="MEDIUM",
        note=f"통로 장애물 감지 (거리 {distance}px) — robot-sim",
        source="robot-sim",
    )


def _make_on_scan(world, scanned_ids):
    def on_scan(location):
        items_here = world.items_at(location)
        names = ", ".join(it["name"] for it in items_here) if items_here else "(빈 선반)"
        world.note(f"{location} 확인: {names}")
        for it in items_here:
            scanned_ids.add(it["id"])
    return on_scan


def _submit(world, scanned_ids, all_items):
    """스캔한 결과와 (시작할 때 불러온) 전체 물품 목록을 로컬에서 비교해 불일치를 계산한다.

    예전엔 이 결과를 실제 audit_sessions DB에 기록했지만, 그 경로(로컬 FastAPI 서버)가
    더 이상 존재하지 않아서 일단 로컬 계산까지만 한다 — DB 기록(run_inventory_audit RPC
    연동)은 다음 단계에서 붙일 예정이라 여기서 "완료됐다"고 표시하지 않는다.
    """
    if not all_items:
        world.note("비교할 물품 목록이 없습니다 — 웹 연동(.env) 확인 후 다시 실행하세요")
        return
    if not scanned_ids:
        world.note("제출할 스캔 기록이 없습니다 — 먼저 순찰하세요")
        return
    missing = [it for it in all_items if it["id"] not in scanned_ids]
    world.note(
        f"실사 결과(로컬 계산): {len(scanned_ids)}건 확인, 불일치 {len(missing)}건 "
        "— DB 기록은 아직 안 됨"
    )
    for it in missing:
        world.note(f"  불일치: {it['name']} ({it['location']}) — 실사 시 미확인")


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("LabKeeper Robot Sim — 실사 순찰 연습")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("malgungothic", 16)

    items = fetch_items()
    world = World(items=items)
    if items:
        world.note(f"웹에서 물품 {len(items)}개, 체크포인트 {len(world.markers)}개 불러옴 (Supabase)")
    elif not is_configured():
        world.note("robot-sim/.env 미설정 — 체크포인트 없이 이동/장애물만 연습 (.env.example 참고)")
    else:
        world.note("웹 물품 목록 없음(Supabase 연결 실패 또는 items 비어있음) — 체크포인트 없이 연습")

    scanned_ids = set()
    hal = SimHAL(world)
    controller = PatrolController(
        hal,
        on_scan=_make_on_scan(world, scanned_ids),
        on_obstacle=lambda d: _on_obstacle(world, d),
        on_obstacle_cleared=lambda: world.note("장애물 제거됨 — 순찰 재개"),
    )

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    world.add_obstacle_ahead()
                    world.note("장애물 추가")
                elif event.key == pygame.K_c:
                    world.clear_obstacles()
                    world.note("장애물 전체 제거")
                elif event.key == pygame.K_r:
                    world.robot.reset()
                    world.note("로봇 위치 리셋")
                elif event.key == pygame.K_m:
                    removed = world.hide_random_item()
                    if removed:
                        scanned_ids.discard(removed["id"])
                        world.note(f"몰래 없어짐: {removed['name']} ({removed['location']})")
                    else:
                        world.note("숨길 물품이 없습니다")
                elif event.key == pygame.K_f:
                    _submit(world, scanned_ids, items)
                elif event.key == pygame.K_n:
                    scanned_ids.clear()
                    world.note("스캔 기록 초기화 — 새 실사 시작")

        controller.tick(dt)
        world.robot.step(dt)

        draw(screen, world, font)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
