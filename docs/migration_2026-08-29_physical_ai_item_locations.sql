-- LabBot Physical AI 물품 위치 스키마 전환
-- 목적: 별도 대여/반납실 없이 실제 실험실의 구역·선반·단·칸과 안내 좌표를 저장한다.
-- QR 원문은 이 테이블이나 USD에 복제하지 않는다. QR 최종 검증은 기존 items/대여 RPC가 담당한다.

begin;

alter table public.virtual_lab_objects
  add column if not exists zone_type text,
  add column if not exists access_level text,
  add column if not exists shelf_code text,
  add column if not exists shelf_row integer,
  add column if not exists shelf_slot integer,
  add column if not exists location_detail text,
  add column if not exists nav_x double precision,
  add column if not exists nav_y double precision,
  add column if not exists nav_heading double precision;

alter table public.virtual_lab_objects
  drop constraint if exists virtual_lab_objects_zone_type_check;
alter table public.virtual_lab_objects
  add constraint virtual_lab_objects_zone_type_check
  check (zone_type is null or zone_type in ('lab_inventory', 'restricted_lab'));

alter table public.virtual_lab_objects
  drop constraint if exists virtual_lab_objects_access_level_check;
alter table public.virtual_lab_objects
  add constraint virtual_lab_objects_access_level_check
  check (access_level is null or access_level in ('authorized', 'staff'));

alter table public.virtual_lab_objects
  drop constraint if exists virtual_lab_objects_shelf_row_check;
alter table public.virtual_lab_objects
  add constraint virtual_lab_objects_shelf_row_check
  check (shelf_row is null or shelf_row > 0);

alter table public.virtual_lab_objects
  drop constraint if exists virtual_lab_objects_shelf_slot_check;
alter table public.virtual_lab_objects
  add constraint virtual_lab_objects_shelf_slot_check
  check (shelf_slot is null or shelf_slot > 0);

update public.virtual_lab_objects set
  room = '일반실험실', zone_type = 'lab_inventory', access_level = 'authorized',
  shelf_code = 'LAB-G04', shelf_row = 2, shelf_slot = 1,
  location_detail = 'LAB-G04 IslandEast 실험대 2번째 줄, 왼쪽 1번째 스탠드',
  nav_x = 2.60, nav_y = 5.55, nav_heading = 0
where scene_object_id = 'eq-pipette-01';

update public.virtual_lab_objects set
  room = '소모품보관실', zone_type = 'lab_inventory', access_level = 'authorized',
  shelf_code = 'LAB-CON-01', shelf_row = 2, shelf_slot = 3,
  location_detail = 'LAB-CON-01 소모품 선반 2번째 줄, 왼쪽에서 3번째 바구니',
  nav_x = 1.80, nav_y = 10.00, nav_heading = 0
where scene_object_id = 'con-tips-01';

update public.virtual_lab_objects set
  room = '일반실험실', zone_type = 'lab_inventory', access_level = 'authorized',
  shelf_code = 'LAB-G03', shelf_row = 1, shelf_slot = 1,
  location_detail = 'LAB-G03 IslandEast 실험대 1번째 줄, 오른쪽 1번째 위치',
  nav_x = 2.60, nav_y = 2.35, nav_heading = 0
where scene_object_id = 'eq-centrifuge-01';

update public.virtual_lab_objects set
  room = '일반실험실', zone_type = 'lab_inventory', access_level = 'authorized',
  shelf_code = 'LAB-G02', shelf_row = 2, shelf_slot = 2,
  location_detail = 'LAB-G02 IslandWest 실험대 2번째 줄, 왼쪽 2번째 위치',
  nav_x = -2.60, nav_y = 5.72, nav_heading = 0
where scene_object_id = 'eq-scale-01';

update public.virtual_lab_objects set
  room = '일반실험실', zone_type = 'restricted_lab', access_level = 'authorized',
  shelf_code = 'LAB-G01', shelf_row = null, shelf_slot = null,
  location_detail = 'LAB-G01 메인 실험대 현미경 스테이션',
  nav_x = -2.35, nav_y = 2.10, nav_heading = 0
where scene_object_id = 'eq-microscope-01';

update public.virtual_lab_objects set
  room = '기기실-1', zone_type = 'restricted_lab', access_level = 'authorized',
  shelf_code = 'LAB-I01', shelf_row = null, shelf_slot = null,
  location_detail = 'LAB-I01 기기실-1 PCR 장비 전용 실험대',
  nav_x = -1.80, nav_y = 10.00, nav_heading = 0
where scene_object_id = 'eq-pcr-01';

update public.virtual_lab_objects set
  room = '시약보관실', zone_type = 'restricted_lab', access_level = 'authorized',
  shelf_code = 'LAB-R01', shelf_row = null, shelf_slot = null,
  location_detail = 'LAB-R01 시약조제대 pH 측정 스테이션',
  nav_x = 0.00, nav_y = 13.60, nav_heading = 0
where scene_object_id = 'eq-phmeter-01';

update public.virtual_lab_objects set
  room = '냉동보관실', zone_type = 'restricted_lab', access_level = 'authorized',
  shelf_code = 'LAB-F01', shelf_row = null, shelf_slot = null,
  location_detail = 'LAB-F01 냉동보관실 첫 번째 -80℃ 초저온 냉동고',
  nav_x = 1.80, nav_y = 14.60, nav_heading = 0
where scene_object_id = 'eq-freezer-01';

update public.virtual_lab_objects set
  room = '시약보관실', zone_type = 'restricted_lab', access_level = 'authorized',
  shelf_code = 'LAB-R02', shelf_row = null, shelf_slot = null,
  location_detail = 'LAB-R02 노란색 인화성 물질 안전 캐비닛 내부',
  nav_x = 0.00, nav_y = 13.60, nav_heading = 0
where scene_object_id = 'reagent-ethanol-01';

update public.virtual_lab_objects set
  room = '안전장비구역', zone_type = 'restricted_lab', access_level = 'staff',
  shelf_code = 'LAB-S01', shelf_row = null, shelf_slot = null,
  location_detail = 'LAB-S01 남동쪽 출입구 벽면 소화기 거치대',
  nav_x = 0.00, nav_y = 0.00, nav_heading = 0
where scene_object_id = 'saf-extinguisher-01';

create index if not exists virtual_lab_objects_item_location_idx
  on public.virtual_lab_objects (item_id, shelf_code)
  where enabled = true;

commit;
