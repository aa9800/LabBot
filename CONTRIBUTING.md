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
