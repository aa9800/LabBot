# LabBot — 연구실 물품 대여·재고·안전 관리 프로젝트

**피지컬 AI 기초 · 로보카 프로젝트**

## 저장소 구조

```
docs/          설계문서·계획서·기능요구사항·DB 스키마 — 팀 전체 참고자료
robot-sim/     Raspbot 실물 도착 전 연습용 시뮬레이터 (라인트래킹/장애물/QR/실사/Safety)
```

웹(실제 서비스 화면)은 별도로 새로 만들고 있으며, 완성되면 `web/` 폴더로 이 저장소에 합류할 예정입니다.

## 문서 가이드 — 어디부터 볼지

| 문서 | 용도 |
|---|---|
| `docs/LabBot_기능요구사항.html` | **웹 개발 시작할 때 여기부터.** 데이터 모델·기능 로직 정리 (최신본) |
| `docs/labbot_schema.sql` | Supabase SQL Editor에 붙여넣을 DB 스키마 (테이블+RLS 정책, 최신본) |
| `docs/LabKeeper_설계문서.html` | 전체 아키텍처, 로봇 연동, Safety 모듈 설계 (장기 참고용) |
| `docs/LabKeeper_프로젝트계획서.html` | 일정, 역할분담, 예산 |
| `docs/LabKeeper_브리핑.html` | 프로젝트 쉬운 소개 자료 |
| `docs/LabFlow_LabKeeper_실행현실화_기획서_v1.2.docx` | 안전관리 기획 최종본 (v1.0·v1.1은 v1.2에 통합되어 삭제됨) |

옛 FastAPI 프로토타입(`labkeeper-web-local/`, git 미포함) 전용 문서인 `LabKeeper_웹기능명세서.html`은 그 폴더로 옮겼습니다.

## robot-sim 실행

```bash
cd robot-sim
pip install -r requirements.txt
python main.py
```

자세한 조작법과 웹 연동 방법은 `robot-sim/README.md` 참고.

## 협업 방법

`CONTRIBUTING.md` 참고.

## 팀

| 이름 | 역할 |
|---|---|
| 여해동 | Raspberry Pi / 로보카 (robot-sim, 실물 연동) |
| 김지훈 | Web / DB |
