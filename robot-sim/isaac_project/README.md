# LabKeeper Isaac Sim 디지털 트윈

고정 환경은 `assets/labkeeper_lab_v2.usda`, 제어·센서·Supabase 연동은 Standalone Python으로 분리한다. 장면은 방안 2(화학·바이오 실험실)를 중심으로 하고, 방안 1의 클린 복도와 유리 파티션을 결합했다.

## 구성

- 10개 구역: 오픈형 일반실험실, 기기실-1/2, 세포배양실, 시약/냉장/냉동/소모품 보관실, 안전장비함, 대여·반납실
- 14 x 26 m 확장 평면, 보안 유리 경계와 출입 리더, 대여 선반 A/B, 반납 데스크, 충전 도크
- 실제형 모듈 실험대·하부장·싱크·서비스 포트와 1.8 m 중앙 이동 통로
- NVIDIA Isaac 6.0 Hospital SimReady의 카트·의자·캐비닛·병·폐기물통을 인스턴스로 혼합
- 대표 물품만 3D로 표시하고 `scene_object_id -> virtual_lab_objects.item_id -> items.id`로 실제 재고를 조회
- 웹에서 대여 안내를 시작하면 DB 물품의 지정 좌표 또는 카테고리 기본 선반으로 로봇이 자동 이동
- QR은 특정 장소에 고정하지 않고, 사용자가 물품을 로봇 카메라 앞에 보여 주는 순간 가상/실물 모두 대여·반납 확정
- 4륜 스키드 스티어 Raspbot, 실측 바퀴 지름 6.5 cm·트랙 폭 13.5 cm
- 웹에서 실물/Isaac 타깃 전환 후 주행·회전·Pan/Tilt·QR 스캔을 같은 UI로 제어
- 마지막 수동 명령 후 1초가 지나면 자동 정지하는 deadman 적용

## 실행

프로젝트 루트에서:

```powershell
$env:HEADLESS='0'
& 'C:\Users\a9800\isaac_clean\venv\Scripts\python.exe' '.\robot-sim\isaac_project\run_isaac.py'
```

RTX 5070에서는 기본으로 `high`(실시간 레이트레이싱 + DLSS Quality), 1600×900 창,
960×540 FPV, JPEG 84를 사용한다. 프레임이 부족하면 품질만 낮출 수 있다.

```powershell
$env:LABKEEPER_RENDER_QUALITY='balanced' # performance / balanced / high / cinematic
$env:LABKEEPER_FPV_WIDTH='960'
$env:LABKEEPER_FPV_HEIGHT='540'
$env:LABKEEPER_STREAM_EVERY_N_TICKS='1' # 1=매 렌더 틱, 2=CPU/네트워크 절약
```

`cinematic` 프리셋은 정지 스크린샷용 Path Tracing이며 로봇 조작 중에는 `high`를 권장한다.

성능 우선으로 NVIDIA 온라인 장식 에셋을 끄려면 실행 전에 다음 값을 설정한다. 로컬 v2 연구실과 모든 기능은 그대로 유지된다.

```powershell
$env:LABKEEPER_SIMREADY_DETAILS='0'
```

장면을 다시 생성하거나 자동 검증하려면:

```powershell
& 'C:\Users\a9800\isaac_clean\venv\Scripts\python.exe' '.\robot-sim\isaac_project\build_lab_asset.py'
& 'C:\Users\a9800\isaac_clean\venv\Scripts\python.exe' '.\robot-sim\isaac_project\lab_scene_smoke_test.py'
```

Supabase SQL Editor에서 `docs/labbot_schema.sql`의 32번 섹션을 적용해야 가상 스캔 RPC가 활성화된다. 이어서 33번 섹션을 적용하면 모든 DB 물품의 가상 바인딩, 선반 좌표와 `robot_guide_tasks` 이력이 활성화된다. QR 원문은 브라우저나 USD에 저장하지 않는다.

물품별 목적지는 `scene/guide_targets.json`에서 관리한다. 대표 3D 물품은 개별 좌표를 사용하고 나머지 재고는 DB의 `item_type`과 `location`에 따라 가장 가까운 대여 선반 또는 제한 구역 안내 지점으로 연결된다.
