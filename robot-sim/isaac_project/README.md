# LabKeeper Isaac Sim 디지털 트윈

고정 환경은 `assets/labkeeper_lab_v2.usda`, 제어·센서·Supabase 연동은 Standalone Python으로 분리한다. 장면은 방안 2(화학·바이오 실험실)를 중심으로 하고, 방안 1의 클린 복도와 유리 파티션을 결합했다.

## 구성

- 9개 연구실 구역 + 입구 공용비품 구역: 일반실험실, 기기실-1/2, 세포배양실, 시약/냉장/냉동/소모품 보관실, 안전장비구역
- 입구를 포함한 14 x 26 m 전체 평면, 보안 유리 경계와 출입 리더, 실제 실험대·보관 선반·로봇 이동 통로
- 실제형 모듈 실험대·하부장·싱크·서비스 포트와 1.8 m 중앙 이동 통로
- NVIDIA Isaac 6.0 Hospital SimReady의 카트·의자·캐비닛·병·폐기물통을 인스턴스로 혼합
- 대표 물품만 3D로 표시하고 `scene_object_id -> virtual_lab_objects.item_id -> items.id`로 실제 재고를 조회
- 웹에서 대여 안내를 시작하면 DB 물품의 지정 좌표 또는 카테고리 기본 선반으로 로봇이 자동 이동
- QR은 특정 장소에 고정하지 않고, 사용자가 물품을 로봇 카메라 앞에 보여 주는 순간 가상/실물 모두 대여·반납 확정
- 4륜 스키드 스티어 Raspbot, 실측 바퀴 지름 6.5 cm·트랙 폭 13.5 cm
- 웹에서 실물/Isaac 타깃 전환 후 주행·회전·Pan/Tilt·QR 스캔을 같은 UI로 제어
- 동적 장애물과 USD 벽·파티션·고정 가구를 구분해 감지하고, 공통 상태기계로 좌우 공간을 스캔한 뒤 기존 웨이포인트로 복귀
- Isaac 전용 자동순찰은 입구 공용비품 구역부터 보안 연구구역의 서측·북측·동측 통로를 한 바퀴 돌아 출발점으로 복귀하며, 실물 Raspbot 경로와 완전히 분리
- 관리자 안전이벤트의 `좌표 순찰`에서 기본 대상 `아이작 심`을 선택하면 `/patrol/map`으로 23개 지점 경로를 불러오고, 시작·중지·현재 좌표·진행 지점을 실시간 제어/확인
- Isaac의 강제정지는 새 명령 전까지 유지되며, 대기 자리 복귀는 현재 순찰선의 앞/뒤 중 짧은 안전 경로를 선택한다. 연속·15/30/60분 자동반복은 브라우저가 아닌 Isaac 서버가 관리
- 웹 가상실험실의 `/lab_preview`는 로봇 FPV와 분리된 1280×720 RTX 카메라로 현재 USD 장면을 직접 렌더링
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
$env:LABKEEPER_ISAAC_AUTO_PATROL='1' # 1=실행 즉시 전체 연구실 자동순찰, 0=대기
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

기존 Supabase에 위치 상세 컬럼이 없다면 SQL Editor에서 `docs/migration_2026-08-29_physical_ai_item_locations.sql`을 적용한다. QR 원문은 브라우저나 USD에 저장하지 않는다.

물품별 가상 목적지는 `scene/guide_targets.json`에서 관리한다. 대표 3D 물품은 개별 좌표를 사용하고 나머지 재고는 DB의 `item_type`과 `location`에 따라 실제 실험실 보관 구역의 기본 안내 지점으로 연결된다. 실물 바닥 주행 경로는 별도 캘리브레이션이 끝나기 전까지 자동 모터 명령으로 실행하지 않는다.
