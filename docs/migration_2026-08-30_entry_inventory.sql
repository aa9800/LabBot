-- LabBot 입구 공용비품 보관구역 ↔ Isaac 물품 ↔ 로봇 좌표 정합화
-- 재고 원본은 items, 장면/선반/안내 좌표는 virtual_lab_objects가 담당한다.
-- 장식 가구·서비스대·키오스크·로봇 도크는 USD fixture로만 유지하고 재고로 복제하지 않는다.

begin;

-- 실제 입구 선반에 3D 모델이 존재하는 대표 물품만 입구 공용비품으로 이동한다.
with desired(name, storage_position) as (
  values
    ('마이크로피펫 세트', 'ENT-W01 · 3단 · 1칸'),
    ('10 μL 피펫 팁', 'ENT-W02 · 3단 · 1칸'),
    ('200 μL 피펫 팁', 'ENT-W02 · 3단 · 2칸'),
    ('1000 μL 피펫 팁', 'ENT-W02 · 3단 · 3칸'),
    ('마이크로 원심분리기', 'ENT-E01 · 3단 · 1칸'),
    ('전자저울', 'ENT-E02 · 3단 · 2칸')
)
update public.items i
set location = '입구 공용비품 보관구역',
    storage_parent_item_id = null,
    storage_position = desired.storage_position
from desired
where i.name = desired.name;

-- db-item-* 일반 선반 행과 과거 대표 행을 먼저 정리해 물품당 활성 안내 위치를 하나로 만든다.
delete from public.virtual_lab_objects v
using public.items i
where v.item_id = i.id
  and i.name in (
    '마이크로피펫 세트', '10 μL 피펫 팁', '200 μL 피펫 팁',
    '1000 μL 피펫 팁', '마이크로 원심분리기', '전자저울'
  );

with desired(
  item_name, scene_object_id, display_mode, shelf_code, shelf_row, shelf_slot,
  location_detail, nav_x, nav_y, nav_heading
) as (
  values
    ('마이크로피펫 세트', 'eq-pipette-01', 'single', 'ENT-W01', 3, 1,
      'ENT-W01 입구 서측 개방 선반 3단, 왼쪽 1번째 피펫 스탠드', -2.60, -5.22, 180.0),
    ('10 μL 피펫 팁', 'con-tips-01', 'single', 'ENT-W02', 3, 1,
      'ENT-W02 입구 서측 개방 선반 3단, 왼쪽 1번째 바구니', -2.60, -6.47, 180.0),
    ('200 μL 피펫 팁', 'con-tips-02', 'single', 'ENT-W02', 3, 2,
      'ENT-W02 입구 서측 개방 선반 3단, 왼쪽 2번째 바구니', -2.60, -6.47, 180.0),
    ('1000 μL 피펫 팁', 'con-tips-03', 'single', 'ENT-W02', 3, 3,
      'ENT-W02 입구 서측 개방 선반 3단, 왼쪽 3번째 바구니', -2.60, -6.47, 180.0),
    ('마이크로 원심분리기', 'eq-centrifuge-01', 'single', 'ENT-E01', 3, 1,
      'ENT-E01 입구 동측 개방 선반 3단, 오른쪽 1번째 위치', 2.60, -5.22, 0.0),
    ('전자저울', 'eq-scale-01', 'single', 'ENT-E02', 3, 2,
      'ENT-E02 입구 동측 개방 선반 3단, 오른쪽 2번째 위치', 2.60, -6.48, 0.0)
)
insert into public.virtual_lab_objects (
  scene_object_id, item_id, room, display_mode, enabled, zone_type, access_level,
  shelf_code, shelf_row, shelf_slot, location_detail, nav_x, nav_y, nav_heading
)
select
  desired.scene_object_id, i.id, '입구 공용비품 보관구역', desired.display_mode, true,
  'lab_inventory', 'authorized', desired.shelf_code, desired.shelf_row, desired.shelf_slot,
  desired.location_detail, desired.nav_x, desired.nav_y, desired.nav_heading
from desired
join public.items i on i.name = desired.item_name
on conflict (scene_object_id) do update set
  item_id = excluded.item_id,
  room = excluded.room,
  display_mode = excluded.display_mode,
  enabled = excluded.enabled,
  zone_type = excluded.zone_type,
  access_level = excluded.access_level,
  shelf_code = excluded.shelf_code,
  shelf_row = excluded.shelf_row,
  shelf_slot = excluded.shelf_slot,
  location_detail = excluded.location_detail,
  nav_x = excluded.nav_x,
  nav_y = excluded.nav_y,
  nav_heading = excluded.nav_heading;

commit;

