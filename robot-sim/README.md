# LabKeeper Robot: Raspberry Pi 5 Physical AI 전환

이 폴더(`robot-sim/`)에는 Raspberry Pi 5 Raspbot의 하드웨어 제어, 카메라, 센서, QR, 임무·야간경비 엔진과 로봇 내장형 Physical AI 코드가 있습니다. 통합 YOLO11 NCNN 추론과 웹 API는 실물 Pi에서 동작하며, 자동 AI 행동은 실제 데이터 검증 전까지 Shadow Mode로 잠겨 있습니다.

## ⚙️ 목표 동작 방식

1. **카메라 캡처**: Picamera2가 실시간 영상을 촬영합니다.
2. **AI 분석 (로봇 내부)**: 하나의 NCNN 모델이 사람과 연구실 물품을 비동기로 감지합니다. HOG는 추론 오류 시 보조 fallback일 뿐 정상 운영 경로가 아닙니다.
3. **자율 행동**: 초음파 정지와 행동 우선순위가 AI보다 먼저 적용됩니다. 자동 사람 추적은 별도 안전 검증 전에는 활성화하지 않습니다.
4. **스트리밍 송출**: 로봇이 원본 영상과 분석 결과를 `:8080`에서 직접 송출합니다.

---

## 🚀 실행 방법

### 라즈베리파이 로봇 켜기
라즈베리파이에 SSH로 접속하거나 로봇에서 직접 터미널을 열고 실행합니다.

전원을 켜면 `labkeeper-robot.service`가 자동 시작됩니다.

```bash
systemctl status labkeeper-robot.service
journalctl -u labkeeper-robot.service -f
```

수동 개발 실행이 필요하면 먼저 서비스를 중지하고 전용 venv를 사용합니다.

```bash
sudo systemctl stop labkeeper-robot.service
cd /home/pi/labkeeper
/home/pi/labkeeper-edge-venv/bin/python -u run_real.py
```

### 웹 콘솔 켜기
동일한 네트워크에 연결된 노트북이나 PC에서 `web/` 폴더를 로컬 웹 서버로 띄웁니다.
```bash
cd LabKeeper/web
python -m http.server 3000
```
> 브라우저에서 `http://localhost:3000` 으로 접속하면 실시간 AI 로봇 콘솔과 디지털 트윈 화면을 확인할 수 있습니다.

---

## 🧠 내부 모듈 구성

- **`run_real.py`**: 실물 로봇 실행 진입점. 제어·AI·임무·서버의 생명주기와 안전 종료를 통합 관리합니다.
- **`controller.py` & `real_hal.py`**: 초음파 회피, 라인트래킹, 모터 등 순수 하드웨어 제어.
- **`frame_broker.py`**: 카메라를 한 번만 열고 원본 스트림·AI·QR에 최신 프레임을 공유합니다.
- **`edge_inference.py`**: NCNN 최신 프레임 비동기 추론과 감지 결과를 제공합니다.
- **`mission_engine.py`**: DB 동기화 위치 캐시로 물품 안내 임무와 연속 목적지를 관리합니다.
- **`collect_real_lab_data.py`**: 로봇이 정지해 있고 촬영 권한이 확인된 경우에만 실제 연구실 원본 이미지를 로컬 수집합니다.
- **`health_monitor.py`**: 카메라/AI FPS, 온도, 스로틀링, 메모리, 서비스 재시작을 장시간 JSONL로 기록합니다.
- **`night_guard.py`**: 주간 대여 보조와 야간 예약 순찰/센서 트리거 상태를 관리합니다.
- **`stream_server.py`**: 카메라·제어·AI·QR·물품 안내 API를 `:8080`에서 제공합니다.
- **`ai_vision/`**:
  - `detector.py`: RTX 학습·검증용 YOLO 객체 탐지 모듈.
  - `safety_engine.py`: 화재 안전, 시약 방치 등 위험 요소 판단.
  - `intruder_tracker.py`: 침입자 감지 시 추적 수치 계산.

---

## 실제 연구실 데이터 수집

수집 전에 로봇을 `manual`, 속도 0, 회전 0으로 정지합니다. 아래 도구는 각 이미지 직전에 이 조건을 다시 확인하며, 위반 시 즉시 중단합니다. 이미지는 로컬에만 저장되고 자동 업로드나 자동 라벨링은 하지 않습니다.

빈 배경·벽·가구 음성 샘플(탐지 대상이 없는 이미지):

```bash
/home/pi/labkeeper-edge-venv/bin/python collect_real_lab_data.py \
  --purpose background-negative --count 30 --interval-seconds 1 \
  --site-authorization-confirmed
```

사람 검증 데이터는 연구실 촬영 권한과 촬영 대상자의 명시적 동의를 모두 확인해야 합니다.

```bash
/home/pi/labkeeper-edge-venv/bin/python collect_real_lab_data.py \
  --purpose person-validation --count 30 --interval-seconds 1 \
  --site-authorization-confirmed --person-consent-confirmed
```

수집 결과는 기본적으로 `datasets/real_lab/<세션>/`에 JPEG와 `manifest.jsonl`로 저장됩니다.

## 30분 내구성 기록

```bash
/home/pi/labkeeper-edge-venv/bin/python health_monitor.py \
  --duration-seconds 1800 --interval-seconds 30 --min-ai-fps 9 \
  --output logs/endurance_30min.jsonl
```

마지막 JSONL 레코드의 `pass`는 API 오류 없음, 서비스 재시작 없음, 스로틀링 없음, 전 구간 AI 9 FPS 이상을 모두 만족해야 `true`가 됩니다.
