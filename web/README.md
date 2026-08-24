# LabKeeper — 웹 전용 MVP

실습실 물품 대여·재고관리 웹 서비스의 **1주차 범위(웹 MVP)** 구현체입니다.
로봇(Raspbot)·아두이노 연동은 이번 범위에 포함하지 않았고, 나중에 그대로 붙일 수 있도록 `/api` 아래에 뼈대만 미리 열어뒀습니다.

## 구현된 기능

- 물품 등록 / 검색(카테고리·위치·키워드) / QR코드 자동 발급
- 대여 · 반납 처리, 연체일 자동 계산
- 재고 실사 — 체크리스트 방식(로봇 연동 전까지의 임시 방식, 체크 안 된 물품은 자동으로 "불일치" 기록)
- 대시보드 — 전체 재고, 대여중, 연체 건수, 최근 실사 정확도, 인기 물품, 미조치 Safety 이벤트
- **Safety 이벤트** — `robot-sim`이 감지한 이상(예: 통로 장애물)을 접수해 감지→검토→배정→조치→해결→종결의 폐쇄루프로 관리 (LabFlow v1.2 14장의 축소 데이터모델 채택)

인증/로그인은 이번 범위에서 의도적으로 생략했습니다. 대여 화면에서 사용자를 드롭다운으로 선택하는 방식이며, 실사용 배포 전에는 로그인이나 RFID 인증을 붙여야 합니다.

## 실행 방법

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

브라우저에서 http://127.0.0.1:8000 접속. 최초 실행 시 데모 데이터(사용자 3명, 물품 8종)가 자동으로 채워집니다.

## 구조

```
labkeeper-web/
  app/
    main.py            FastAPI 앱 진입점 (lifespan에서 데모 데이터 시딩)
    database.py         DB 연결 (SQLite, labkeeper.db)
    models.py           데이터 모델 (User / Item / Loan / AuditSession / AuditMismatch / SafetyEvent / ActionLog)
    schemas.py           API 요청/응답 스키마
    crud.py              비즈니스 로직 (화면·API가 공통으로 사용)
    qr.py                QR 이미지 생성
    seed.py               데모 데이터
    routers/
      pages.py            화면(HTML) 라우트
      api.py              로봇 등 이후 연동을 위한 JSON API
    templates/            Jinja2 템플릿
    static/                CSS, 생성된 QR 이미지
```

## 이후 단계와의 연결

- `/api/items`, `/api/loans`, `/api/stats/overview`, `/api/safety-events`, `/api/audit-sessions`가 구현돼 있습니다. `/api/gate/tap`(아두이노 게이트)만 아직 없습니다 — 실물 도착 후 추가하면 됩니다.
- `/api/audit-sessions`는 `LabKeeper/robot-sim`이 이미 실제로 호출해서 검증했습니다 — 사람이 `/audits/new` 체크리스트로 하는 것과 완전히 같은 `crud.create_audit_session` 로직을 그대로 탑니다.
- `crud.return_loan_by_qr`은 물품 QR만으로 반납을 확정하는 함수로, 아두이노 게이트를 붙일 때 바로 재사용할 수 있게 미리 만들어 뒀습니다(현재 화면에는 아직 연결하지 않음).
- `/api/safety-events`는 `LabKeeper/robot-sim`이 이미 호출하고 있습니다. 실제 Raspbot이 오면 `real_hal.py`에서 같은 엔드포인트를 호출하도록 바꾸면 됩니다 — 웹 쪽은 수정할 필요가 없습니다.
- SR-05/06/07(위치·재고 불일치, 점검누락)은 별도 SafetyEvent를 만들지 않고 기존 `AuditMismatch`가 그대로 담당합니다 — 중복 구현하지 않았습니다.
