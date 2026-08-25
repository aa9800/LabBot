# CHANGELOG

이 파일은 지우지 않고 계속 누적합니다. **커밋/푸시할 때마다 맨 위에 새 항목을 추가**하세요
(날짜 + 무엇을 왜 바꿨는지 한두 줄). 오래된 항목도 지우지 않습니다 — 전체 이력이 남아있어야
나중에 "언제부터 이게 이랬지?"를 추적할 수 있습니다.

---

## 2026-08-25 (3) — UX 검토(물품목록/관리자) + Safety RPC + 보안 점검 + Edge Function 소스 백업

**커밋**: 이 항목을 추가한 커밋 (여해동님 자리 비운 사이 자동 진행 — GPT 리뷰(`labkeeper-web-local/AI협업/01_GPT_최신리뷰.md`)와 겹치는 항목 다수, 겹치지 않는 것도 있음)

### 물품목록(items.html) 사용자 편의성 개선
- 물품이 많아지면서 페이지가 한없이 길어지던 문제 — 12개 단위 페이지네이션 추가
  (검색/필터 바뀌면 1페이지로 리셋).
- 물품 사진을 개별로 관리하지 않는 대신, 분류(장비/시약/소모품/PPE/안전물품)별로 자동
  적용되는 아이콘을 추가 — 물품 등록 시 category만 고르면 사람이 사진을 올릴 필요 없이 바로
  적용됨.
- 검색창에 한 글자 입력할 때마다 Supabase에 요청을 보내던 것을 300ms 디바운스로 개선.
- 물품 등록 시 입력한 `notes`(비고)가 그동안 어디에도 표시 안 되고 사라지던 문제 — 물품명에
  마우스 올리면 툴팁으로 보이게 함(관리자 재고표도 동일).

### 관리자 화면 사용성 개선
- 요약 대시보드 카드 추가(등록 물품 종류/재고부족·품절/대여중/파손신고 확인필요/Safety
  검토필요) — 탭을 안 눌러도 지금 뭘 먼저 봐야 하는지 바로 보이고, 클릭하면 해당 탭으로 이동.
- 컬럼이 많은 표(재고표/파손신고 목록)의 가로스크롤이 불편하다는 피드백 — 첫 컬럼(물품명)을
  고정해서 오른쪽으로 스크롤해도 어느 물품 행인지 계속 보이게 함 + 스크롤바를 더 두껍고 잘
  보이게 스타일링.
- Safety 상태 필터에 남아있던 "담당자 배정"(ASSIGNED) 옵션 제거 — 실제로 이 상태가 될 수
  있는 새 이벤트가 없어서 필터에 있어도 항상 결과가 0개였음(DB CHECK 제약에는 과거 데이터
  호환을 위해 남겨둠).

### Safety 상태변경 + 로그기록 원자적 RPC
- DB 함수 `transition_safety_event()` 신설 — 상태 UPDATE와 action_logs INSERT를 하나의 함수
  호출로 묶어서, 하나가 실패하면 둘 다 롤백되게 함(예전엔 두 요청을 따로 보내서 두 번째가
  실패하면 상태만 바뀌고 이력이 안 남을 수 있었음). `web/js/safety-data.js`도 이 RPC를
  호출하도록 교체. NEEDS_REVIEW→OPEN→IN_PROGRESS→RESOLVED 전체 흐름 실제로 돌려서 검증함.

### 보안 점검
- **오픈 리다이렉트 취약점 수정**: `login.html?redirect=...`, `signup.html?redirect=...`의
  redirect 값을 검증 없이 그대로 `location.href`에 넣던 문제 — 로그인 성공 후 외부 사이트로
  보낼 수 있었음. 내부 페이지 허용목록(`index.html`/`items.html`/`mypage.html`/`chatbot.html`/
  `admin.html`)에 없으면 무조건 index.html로 가게 `auth.js`에 `sanitizeRedirect()` 추가.
- **QR 코드 실제 작동 검증**: 전체 물품(61개) qr_code가 DB에서 100% 유일함을 확인(스키마의
  `unique` 제약이 실제로 보장), 임의로 고른 QR 이미지 5개를 별도 디코더(jsQR)로 다시 읽어
  원래 문자열과 정확히 일치하는지 왕복 검증 — 실제로 스캔 가능한 이미지임을 확인함.

### Edge Function 소스 코드를 저장소에 백업
- `gemini-chat`, `gemini-damage-assess`를 Supabase 대시보드 "Via Editor"로만 배포해서
  저장소에 소스가 전혀 없던 문제(GPT 리뷰가 지적) — `supabase/functions/gemini-chat/index.ts`,
  `supabase/functions/gemini-damage-assess/index.ts`로 백업하고 `supabase/functions/README.md`에
  배포 방법·필요 secret 이름을 정리함. 새 Supabase 프로젝트에서도 이 소스로 재현 가능.

### 데이터 점검 중 발견했지만 아직 안 고친 것 (사용자 승인 필요)
- `items` 테이블에 카테고리가 옛날 값(`separation`)으로 남아있는 물품 1개 발견
  (`HPLC 시스템`, item id 48) — 실제 `item_type`은 'EQUIPMENT'로 맞지만 `category`만
  안 바뀌어서 "장비" 필터에 안 뜨고 태그도 "separation"으로 깨져 보임. **이 자동화 세션의
  안전장치가 프로덕션 데이터 UPDATE를 막아서 직접 고치지 못했음** — `update items set
  category = 'EQUIPMENT' where id = 48;` 한 줄이면 고쳐짐. 사용자가 직접 실행하거나
  "해도 된다"고 알려주면 다음에 반영하겠음.
- `items.status`('정상'/'고장'/'폐기') 컬럼이 코드 어디에서도 안 쓰임 — 예전 상태관리
  방식의 잔재로 보임(지금은 `computeStockStatus()`가 대신함). 지우면 스키마 변경이라 일단
  보고만 하고 안 건드림.
- `safety_events.assignee_id`/`due_at` 컬럼도 마찬가지로 코드에서 안 쓰임(ASSIGNED 단계
  제거하면서 같이 죽은 걸로 보임). 스키마 변경 필요해서 역시 보고만 함.

### `labkeeper-web-local/AI협업/` 폴더 확인
- `00_사용방법.md`, `02_Claude_작업요청.md` 확인함. 이 세션 시점 `02_Claude_작업요청.md`는
  "작업 요청 없음" 상태라 GPT 리뷰(`01_GPT_최신리뷰.md`) 내용 중 사용자가 직접 채팅으로
  지시한 것과 겹치는 항목(Safety RPC, 관리자 요약 대시보드, ASSIGNED 정리 등)만 이번에
  반영했고, 그 외 항목(비공개 storage 전환, 파손사진 용량제한, 챗봇 비로그인 안내 등)은
  02번 파일에 사용자가 승인 항목을 적기 전까지 손대지 않음.

### 아직 안 한 것 (다음 차례)
- 위 "데이터 점검 중 발견" 3건 (사용자 승인 대기)
- 실제 Raspbot `RealHAL` 구현 — 실제 하드웨어(GPIO 핀 번호, 모터 드라이버 모델, 카메라 설정)
  없이는 검증 불가능해서 손대지 않음
- `damage-photos`/`robot-camera` storage를 비공개+서명URL 방식으로 전환
- 파손 사진 업로드 용량·MIME 검증

---

## 2026-08-25 (2) — 파손신고 AI 자동판정 + 챗봇 대여/사용 버튼 + QR 이미지 자동생성

**커밋**: 이 항목을 추가한 커밋 (여해동님 자리 비운 사이 자동 진행 — 급격한 구조 변경 없이 기능만 추가)

### 파손 신고 — 제미나이 비전으로 파손 정도 자동 판정
- 사용자가 마이페이지 "대여중인 물품" 카드에서 "파손 신고" 클릭 → 사진 업로드 + 메모 →
  제출 즉시 새 Edge Function `gemini-damage-assess`가 사진을 제미나이 비전에 보내
  **경미/보통/심각/즉시교체** 4단계로 자동 판정하고 요약·권장조치까지 받아온다.
- 결과는 `damage_reports.severity/ai_result/status`에 서버(service role)가 직접 기록 —
  일반 사용자는 이 필드들을 직접 조작할 수 없음 (RLS는 그대로 두고 트리거·서버쪽 쓰기만 허용).
- 관리자 "파손 신고 목록" 탭이 실제 데이터로 렌더링되게 구현 (기존엔 빈 TODO였음) — 물품명/
  신고자/시각/사진링크/AI 판정 배지/AI 분석 요약까지 한 화면에서 확인 가능.
- `damage-photos` 스토리지 버킷 신설(로그인 사용자만 업로드 가능), `damage_reports`에
  `note/status/severity` 컬럼 추가 — `docs/labbot_schema.sql`에 전부 반영.

### 챗봇 — 추천 물품을 버튼으로 바로 사용/대여
- `gemini-chat` 함수가 이제 `{reply, recommended_item_ids}` 구조화된 응답을 돌려주도록 개선
  (전에는 텍스트 답변만 줬음). 프롬프트에 실제 물품 id를 같이 보내고, 서버가 실존하는 id만
  걸러서 돌려주므로 챗봇이 없는 물품을 추천하는 일이 없다.
- 챗봇 화면에 추천 물품이 카드로 뜨고, 소모품이면 "사용하기" / 장비면 "대여하기" 버튼이 바로
  붙어서 대화 중에 바로 처리 가능 (물품목록 페이지로 갈 필요 없음).
- (참고: 작은 소모품 QR 개별 스캔이 힘든 문제는 코드가 아니라 운영 방안으로 논의함 — 묶음
  단위 QR + 챗봇/사용하기 버튼으로 대체하는 방향 제안, 실제 구현은 안 함)

### QR 코드 — 실제 스캔 가능한 이미지 자동 생성
- 관리자 재고표의 QR 코드 칸에 텍스트(`LB-XXXXXXXX`)뿐 아니라 실제 스캔 가능한 QR 이미지를
  자동으로 그려줌 (물품 등록되는 순간 DB 트리거가 발급한 코드를 그 자리에서 바로 이미지화).
  클릭하면 인쇄용 큰 사이즈로 다운로드.

### 버그 수정
- `loans` 조회 시 `items(name, category, location)`만 select해서 **item.id가 항상 undefined**였던
  버그 발견·수정 — 파손 신고 기능 개발 중 발견(대여 카드에서 신고 버튼 눌러도 item_id NULL로
  DB insert가 계속 실패하고 있었음). `LOAN_SELECT`에 `id` 추가.

### 아직 안 한 것 (다음 차례)
- Safety 상태변경 + 로그기록을 원자적 트랜잭션(RPC)으로 묶기
- 관리자 요약 대시보드 카드
- 실제 Raspbot `RealHAL` 구현

---

## 2026-08-25 — 보안 수정 + 생명공학 물품 확장 + 챗봇 연동

**커밋**: `4bee258`, `e855ff7`(지훈님), `ac8faa8`(병합), `da1407c`, 그리고 이 항목을 추가한 커밋

### 보안 수정 (발표 전 필수, GPT 코드리뷰 반영)
- **`profiles.role` 권한 상승 취약점 수정**: 일반 사용자가 API를 직접 호출해 자기 `role`을
  `admin`으로 바꿀 수 있던 문제. DB 트리거(`trg_prevent_role_escalation`)로 관리자가 아니면
  role 변경이 조용히 원상복구되게 막음.
- **`loans` 직접 수정 취약점 수정**: 사용자가 자기 대여 행의 `item_id`/`due_at`/`status`를
  API로 직접 바꿀 수 있던 문제. 트리거(`trg_guard_loan_self_update`)로 "본인 대여를 반납
  처리하는 것"만 허용하고 나머지는 차단.
- **대여 제한을 DB 레벨에서도 검사**: 웹 화면(`computeStockStatus`)에서만 막던 점검중/유효기간
  만료/품절 물품 대여를, DB 트리거(`trg_guard_loan_insert`)로 한 번 더 차단.
- **원격조작(Robot Console) dead-man switch**: 관리자가 수동조작 명령을 보낸 뒤 웹 연결이
  끊겨도 로봇이 마지막 명령을 계속 실행하지 않도록, 명령이 3초 이상 오래되면 자동 정지.

### 생명공학 물품 데이터 확장
- `items` 테이블에 `item_type/unit/minimum_qty/storage_condition/expires_at/manual_status/notes`
  필드 추가.
- 위치를 9개 고정값(일반실험실/기기실-1/기기실-2/세포배양실/시약보관실/냉장보관실/
  냉동보관실/소모품보관실/안전장비함)으로 통일 — 로봇 체크포인트와 어긋나지 않게.
- 생명공학 실험실 물품 60종 시딩 (장비/시약/소모품/PPE/안전물품).
- 재고상태 계산을 `computeStockStatus()` 한 곳(`web/js/items-data.js`)에서만 하도록 정리.
  우선순위: `MAINTENANCE > EXPIRED > OUT_OF_STOCK > EXPIRING_SOON > LOW_STOCK > AVAILABLE`.
- 관리자 물품 등록 폼에 새 필드 입력 UI 추가, 위치는 드롭다운으로 변경.
- 관리자 재고표에 "점검중" 체크박스 + 최소수량 수정 UI 추가.

### 챗봇 — 실제 Gemini 연동
- Supabase Edge Function `gemini-chat` 배포 (제미나이 API 키는 이 함수의 secret에만 저장,
  브라우저 코드에는 절대 노출 안 됨).
- `web/js/chatbot.js`가 실제로 이 함수를 호출하도록 교체 (기존엔 고정 문구만 출력하던 껍데기).
- 지금 등록된 물품 목록을 문맥으로 같이 보내서, 실제 재고에 있는 물품만 추천하게 함.

### 그 외 개선
- 홈 화면 문구를 실제 구현과 맞게 수정("카메라가 알아서 인식" → "물품 대여·재고관리 + 로봇
  순찰 연결"로).
- 대여 완료 시 성공 안내(반납예정일 포함) 표시.
- Safety 이벤트의 "담당자 배정(ASSIGNED)" 단계 제거 — 실제로 담당자를 지정하는 기능 없이
  상태만 바뀌는 게 의미가 없었음. `OPEN → IN_PROGRESS`로 바로 전환.
- 물품명/위치/사용자이름/Safety 메모 등 DB에서 온 문자열을 `innerHTML`에 이스케이프 없이
  넣던 부분(저장형 XSS 위험) 전부 `escapeHtml()` 적용.
- 네브바 여러 페이지에 중복으로 떠 있던 "관리자 로그인" 임시 링크 제거, 정식 "관리자" 링크로
  통일.
- `docs/labbot_schema.sql`에 `robot_commands`/`robot-camera` 스토리지 버킷/보안 트리거 3종을
  전부 문서화 — 새 Supabase 프로젝트에서도 스키마 파일 하나로 재현 가능하게.

### 아직 안 한 것 (다음 차례)
- 파손 신고 탭 실제 구현 (제미나이 비전으로 파손 정도 자동 판정 포함)
- Safety 상태변경 + 로그기록을 원자적 트랜잭션(RPC)으로 묶기
- 관리자 요약 대시보드 카드
- 실제 Raspbot `RealHAL` 구현
