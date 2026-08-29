# LabKeeper — Physical AI 기반 지능형 연구실 자율 방범 로봇

**Raspberry Pi 5 (Raspbot) + NVIDIA Isaac Sim 기반 엣지 Physical AI 전환 프로젝트**

LabKeeper는 위험물이 많은 생명공학 연구실의 **물품 대여/재고 관리**와 **야간 안전/방범 감시**를 돕는 지능형 자율주행 로봇 시스템입니다. 실물 로봇과 디지털 트윈(가상 실험실)을 연동하여 관리자가 웹에서 연구실 상황을 실시간으로 직관적으로 통제할 수 있습니다.

## 📂 저장소 구조

```text
LabKeeper/
├── docs/                     # Physical AI 아키텍처 마스터 설계도 및 DB 스키마
├── robot-sim/                # 로봇 자율주행 제어 및 내장형 AI 비전 엔진 (라즈베리파이용)
│   ├── ai_vision/            # 로봇 내장 AI 엔진 (안전규정 판단, 비주얼 서보잉)
│   ├── isaac_project/        # NVIDIA Isaac Sim 가상 실험실 디지털 트윈
│   └── run_real.py           # Physical AI 메인 통합 실행 루프
├── web/                      # 사용자 웹 프론트엔드 (로봇 콘솔, 물품 관리, SVG 탑다운 맵)
└── supabase/                 # 백엔드 DB 연동
```

## 🛠️ 핵심 아키텍처: 엣지 Physical AI

이 프로젝트는 운영 중 PC AI 서버에 의존하지 않고, **로봇(Raspberry Pi 5)이 현장에서 직접 보고 판단하며 안전하게 움직이는 Physical AI 아키텍처**를 사용합니다. 통합 YOLO11 NCNN 모델, 카메라 프레임 공유, 임무·야간경비 엔진과 `:8080` API가 Pi에서 동작하며 웹의 운영 경로는 PC `:8081`을 사용하지 않습니다. 자동 AI 행동은 실제 연구실 검증 전까지 Shadow Mode가 기본입니다.

1. **지능형 메인 제어 (`run_real.py`)**
   - 로봇 내부에서 자율 주행 제어와 AI 비전 판단을 통합 수행합니다.
   - 장애물 정지·안전 판단은 네트워크나 추론 지연과 분리하며, 사람 자동 추적은 안전 검증 이후에만 적용합니다.
2. **경량화된 내장형 AI 비전**
   - 연구실 물품 10종과 사람을 하나의 YOLO11 nano 모델로 통합하고 **NCNN으로 변환·실기기 측정**했습니다.
   - RTX 5070 PC는 학습·변환에 사용하고, Pi 운영 런타임에는 무거운 학습 프레임워크를 넣지 않는 것을 원칙으로 합니다.
   - Pi 5 실측값은 320 입력·2 threads에서 약 25.6 FPS 추론 가능이며, 지속 운용 열 여유를 위해 AI 10 FPS로 설정합니다. 원본 영상은 약 32 FPS를 유지합니다.
   - 사람 클래스는 초기 부트스트랩 데이터 수준이므로 자동 추적·경보 구동에는 아직 사용하지 않습니다.
3. **디지털 트윈 & 초저지연 웹 관제 (`web/`)**
   - 로봇이 자체 분석한 AI 영상을 PC 추론 서버를 거치지 않고 `:8080`에서 웹으로 직결 송출합니다.
   - NVIDIA Isaac Sim의 실제 좌표 데이터를 웹 SVG 맵에 1:1로 매핑하여 로봇의 위치와 연구실 상태를 한눈에 파악합니다.

## 📄 핵심 문서 안내

| 문서 | 용도 |
|---|---|
| `docs/PHYSICAL_AI_EDGE_TRANSITION_PLAN.md` | **현재 상태, 전환 순서, 완료 기준을 정한 최우선 실행 문서** |
| `docs/LABKEEPER_MASTER_BLUEPRINT.md` | 전체 제품 비전과 개념 설계도 |
| `docs/ARCHITECTURE_PHYSICAL_AI.md` | 목표 Physical AI 아키텍처 참고 문서 |
| `docs/labbot_schema.sql` | Supabase DB 세팅 스키마 파일 |
| `robot-sim/README.md` | 로봇 실행 방법 가이드 |
| `AGENTS.md` | AI 에이전트 작업 가이드 및 규칙 |

## 🚀 시작하기

로봇 실행 방법은 `robot-sim/README.md`를 참고해 주세요. 웹 UI는 `web/` 폴더를 로컬 서버로 띄워 확인하실 수 있습니다.
