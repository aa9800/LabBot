# LabKeeper Robot — 실물 로봇 + 웹 실시간 연동 + Isaac Sim

**2026-08-27부터**: 실제 Raspbot(Raspberry Pi 5)이 도착해서 개발/시연의 중심을
**실물 로봇**으로 옮겼습니다. pygame 연습용 시뮬레이터와 Webots 시뮬레이터는
`_archive_pygame_webots/`로 옮겨두었습니다(삭제는 아님 — 필요하면 꺼내 쓸 수 있게 보관만).

## 핵심 3축

이제부터 데모/개발은 이 세 가지로 통일합니다.

1. **실물 로봇 (Raspbot)** — `real_hal.py` + `run_real.py`
   실제로 라인트래킹/장애물회피/QR스캔이 동작하는 걸 직접 보여주는 축.
2. **웹 실시간 연동** — `stream_server.py` + `notify_supabase.py` + `web/js/robot-console-data.js`
   로봇 상태·카메라·명령이 LabKeeper 웹(Robot Console/안전 이벤트 화면)에 실시간으로
   뜨는 걸 보여주는 축. DB(Supabase)는 명령/Safety 기록의 source of truth로 계속 쓰고,
   카메라만 로컬 MJPEG 직결로 지연을 없앤다.
3. **Isaac Sim** — `isaac_project/`
   실험실 환경을 가상으로 재현해서 디테일(레이아웃, 여러 대 동시 시뮬레이션 등)을
   보여주는 시연용 축. 실물 로봇을 대체하는 게 아니라 "가상 실험실"을 보여주는 용도.

## HAL(하드웨어 추상화) 원칙 — 그대로 유지

```
controller.py         판단 로직. "센서가 이렇게 읽히면 이렇게 움직인다"만 안다.
                       GPIO도, Isaac도 모른다 — 그래서 그대로 재사용된다.
        │
        ├─ real_hal.py           실물 Raspbot (지금의 기본 실행 환경)
        └─ isaac_project/isaac_hal.py   Isaac Sim (가상 실험실 시연용)
```

`controller.py`는 딱 5개 메서드만 있으면 동작합니다: `read_line_sensors()`,
`read_ultrasonic()`, `try_read_qr()`, `set_motion()`, `stop()`. 이 시그니처는
플랫폼이 바뀌어도 절대 안 바꿉니다.

## 실물 로봇 실행

로봇(`~/labkeeper`)에서:

```bash
python3 run_real.py
```

- 카메라: 백그라운드 스레드가 순찰 로직과 무관하게 항상 캡처 → `stream_server.py`가
  `http://<로봇IP>:8080/stream`으로 MJPEG 직결 송출 (Supabase를 거치지 않아 지연이 거의 없음).
- 명령/Safety: 계속 Supabase(`robot_commands`, `safety_events`)를 거친다 — 3초
  dead-man switch, 안전 이벤트 폐쇄루프(`NEEDS_REVIEW → ... → CLOSED`)는 여기서 보장.
- 로봇 자체 핫스팟(인터넷 없음)일 때는 `supabase_relay.py`를 PC에서 띄워 중계 가능
  (파일 상단 주석 참고).

## Isaac Sim 실행

`isaac_project/` 참고 — 런타임은 `C:\Users\a9800\isaac_clean` (Python 3.12.10, Isaac Sim 6.0.1.0).

## 검증(사람 눈 없이 로직만 빠르게 확인)

```bash
python real_hal_smoke_test.py   # RPi.GPIO 등을 mock으로 대체 — PC에서도 모터 믹싱/클램프 로직만 검증
```

GPIO 읽기/쓰기·초음파 타이밍·카메라 캡처처럼 진짜 하드웨어가 있어야 의미 있는 부분은
여기서 검증하지 않습니다 — 로봇 위에서 사람이 직접 확인합니다.

## `_archive_pygame_webots/` — 보관된 이전 시뮬레이터

로봇이 오기 전 순찰 로직을 미리 연습하던 pygame 시뮬레이터(`main.py`, `sim/`,
`check_logic.py`, `smoke_test.py`)와 Webots 프로젝트(`webots_project/`)를 그대로
옮겨뒀습니다. 지금은 협업 범위에서 제외되어 있고(문서:
`labkeeper-web-local/AI협업/robot/00_로봇협업_사용방법.md`), 다시 필요해지면 이
폴더 안 파일들을 `robot-sim/`으로 다시 꺼내면 그대로 동작합니다(코드 자체는 안 건드림).
`requirements.txt`(pygame)도 이 폴더 안에 있습니다.
