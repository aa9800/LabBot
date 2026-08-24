# 협업 방법

팀 3명, 마감이 짧아서 브랜치/PR 리뷰 없이 **바로 main에 push**하는 가벼운 방식으로 갑니다.

## 처음 한 번만

```bash
git clone https://github.com/aa9800/LabBot.git
cd LabBot
```

## 매번 작업할 때

```bash
git pull          # 시작하기 전에 항상 먼저
# ...작업...
git add -A
git commit -m "무슨 작업했는지 한 줄로"
git push          # 끝나면 바로
```

## 충돌을 피하는 규칙

- **각자 건드리는 영역을 분리합니다.**
  - `robot-sim/` — 주로 여해동
  - `web/` — 주로 김지훈 (합류 예정)
  - `docs/` — 누구나, 단 크게 고칠 땐 미리 채팅으로 한마디
- `docs/labbot_schema.sql`처럼 다 같이 참고하는 파일을 고칠 땐 미리 알리고 하기
- `git pull`했는데 "merge conflict"가 뜨면 당황하지 말고 팀 채팅에 바로 공유하기

## 커밋 메시지

형식 강제 없음. 그냥 "뭘 했는지" 한국어로 짧게 쓰면 됩니다.
예: `실사 화면에 불일치 필터 추가`, `robot-sim 장애물 감지 쿨다운 버그 수정`

## 협업자로 초대받기 (저장소 소유자만 할 수 있음)

저장소 소유자(aa9800)가 GitHub에서:
1. https://github.com/aa9800/LabBot/settings/access 접속
2. **Add people** 클릭
3. 초대할 사람의 GitHub 아이디 또는 이메일 입력
4. 초대받은 사람은 이메일/GitHub 알림에서 수락하면 바로 push 권한이 생깁니다

초대 없이도 저장소는 public이라 누구나 clone해서 볼 수 있지만, **push는 협업자로 초대된 사람만** 가능합니다.

## Supabase 협업 방법 (DB 접속 공유)

GitHub 초대와는 **완전히 별개**입니다. 코드는 git으로 공유하고, **데이터(DB)는 다 같이 같은 Supabase 프로젝트에 접속**해서 공유합니다. 그래서 `.env`(진짜 접속 정보)는 git에 올리지 않고, 각자 Supabase에 직접 로그인해서 값을 확인합니다.

### 프로젝트 소유자(지훈님)가 할 일 — 한 번만

1. [supabase.com](https://supabase.com) 대시보드 → 해당 프로젝트 열기
2. **Project Settings → Team**(또는 소속된 Organization의 팀 설정)
3. **Invite member** → 초대할 사람 이메일 입력

### 초대받은 사람이 할 일 — 한 번만

1. 이메일로 온 초대 확인 → 수락 (Supabase 계정 없으면 이때 가입)
2. 로그인 후 그 프로젝트 열기 → **Project Settings → API**
3. **Project URL**, **anon public key** 값을 확인
4. `web/.env.example`을 복사해서 같은 폴더에 `web/.env`로 저장하고, 방금 확인한 값을 채워넣기 (`.env`는 git에 올라가지 않으니 그냥 로컬에 저장하면 됨)

### 지켜야 할 것

- **`service_role` 키는 절대 채팅방·코드·`.env`에도 그냥 붙여넣지 않습니다.** 브라우저에서 실행되는 코드는 전부 anon key만 씁니다. service_role이 정말 필요한 경우(로봇 서버 연동 등)는 지훈님께 개인적으로 별도 요청하세요.
- DB **테이블 구조**를 바꿀 땐(컬럼 추가/삭제 등) 미리 채팅으로 한마디 하기 — 다 같은 DB를 보고 있어서 한 명이 스키마를 바꾸면 전원에게 바로 영향이 갑니다.
- 반대로 **데이터(물품 몇 개 추가 등)** 는 실시간으로 서로 바로 보이니, 그건 자유롭게 테스트하면 됩니다.
