# Supabase Edge Functions — 소스 백업

이 폴더는 Supabase 대시보드의 "Via Editor"로 직접 작성·배포한 Edge Function들의 소스를
**깃에 백업**하기 위한 것입니다. 실제 배포는 여전히 대시보드에서 하지만(아래 "배포 방법"
참고), 코드 자체는 여기가 원본이라고 보고 수정하세요 — 대시보드에서만 고치고 여기 반영을
깜빡하면, 다음에 새 Supabase 프로젝트를 만들거나 배포된 함수가 실수로 지워졌을 때 복구할
방법이 없습니다.

## 함수 목록

| 함수 | 역할 | 필요한 secret |
|---|---|---|
| `gemini-chat` | 챗봇 — 사용자 메시지 + 실제 물품 목록을 받아 제미나이에게 물어보고 `{reply, recommended_item_ids}` 반환 | `GEMINI_API_KEY` |
| `gemini-damage-assess` | 파손 신고 사진을 제미나이 비전으로 분석해서 경미/보통/심각/즉시교체 판정 후 `damage_reports`에 직접 기록 | `GEMINI_API_KEY`, `LABBOT_SERVICE_KEY`(service role key — RLS 우회해서 DB에 결과를 써야 해서 필요) |

두 secret 모두 Supabase 대시보드 → Edge Functions → Secrets에서 등록한다.
`LABBOT_SERVICE_KEY`라는 이름을 쓴 이유: `SUPABASE_`로 시작하는 이름은 예약되어 있어
직접 등록할 수 없다(대시보드가 자동으로 `SUPABASE_URL` 등 기본 secret을 이미 제공).

## 배포 방법 (대시보드)

1. Supabase 대시보드 → Edge Functions → 해당 함수 클릭 → **Code** 탭
2. 이 폴더의 `index.ts` 내용을 전체 복사해서 붙여넣기
3. **Deploy updates** 클릭

CLI로 배포하려면(선택사항, 로컬에 Supabase CLI가 설치되어 있어야 함):

```bash
supabase functions deploy gemini-chat --project-ref <project-ref>
supabase functions deploy gemini-damage-assess --project-ref <project-ref>
```

## 모델 이름 관련 주의

`GEMINI_MODEL`은 `gemini-3.6-flash`로 고정되어 있다. `gemini-2.5-flash`는 신규 사용자에게
더 이상 제공되지 않아(404) 이 버전으로 교체했다. 나중에 또 모델이 deprecated되면
`generativelanguage.googleapis.com/v1beta/models` 목록에서 현재 사용 가능한 모델명을
확인하고 두 파일의 `GEMINI_MODEL` 상수만 바꾸면 된다.
