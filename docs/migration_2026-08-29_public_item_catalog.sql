-- LabBot 공개 물품 카탈로그 조회 정책
--
-- 가상실험실과 물품목록은 로그인 전에도 공개 페이지로 제공된다. items에는 QR 비밀값이
-- 없고(item_qr_codes로 분리되어 관리자만 조회), 대여 이력과 사용자 정보도 포함되지 않는다.
-- 따라서 카탈로그·재고 현황만 anon/authenticated 모두 읽을 수 있게 한다.
-- 등록/수정/삭제는 기존 items_admin_write 정책 그대로 관리자만 가능하다.

drop policy if exists "items_select_all" on public.items;
create policy "items_select_all" on public.items
  for select
  to anon, authenticated
  using (true);

-- 위치 바인딩에는 QR 값이나 사용자 정보가 없으므로 조감도 표시를 위해 공개 조회한다.
drop policy if exists "virtual_lab_objects_select_all" on public.virtual_lab_objects;
create policy "virtual_lab_objects_select_all" on public.virtual_lab_objects
  for select
  to anon, authenticated
  using (enabled = true);

-- 대표 3D 객체가 없는 모든 물품을 최신 Isaac 보관 거점에 바인딩한다.
insert into public.virtual_lab_objects (
  scene_object_id, item_id, room, display_mode, zone_type, access_level, shelf_code,
  shelf_row, shelf_slot, location_detail, nav_x, nav_y
)
select
  'db-item-' || i.id::text,
  i.id,
  i.location,
  'grouped',
  case when i.item_type in ('CONSUMABLE','PPE','SAFETY') then 'lab_inventory' else 'restricted_lab' end,
  'authorized',
  case i.location
    when '일반실험실' then 'LAB-G00'
    when '기기실-1' then 'LAB-I01'
    when '기기실-2' then 'LAB-I02'
    when '세포배양실' then 'LAB-C01'
    when '시약보관실' then 'LAB-R01'
    when '냉동보관실' then 'LAB-F01'
    when '냉장보관실' then 'LAB-F02'
    when '소모품보관실' then 'LAB-CON'
    when '안전장비함' then 'LAB-S'
  end,
  ((i.id - 1) / 4)::integer % 3 + 1,
  ((i.id - 1) % 4)::integer + 1,
  i.location || ' 번호표 ' || i.id::text,
  case
    when i.location in ('기기실-1','기기실-2','세포배양실') then -1.8
    when i.location in ('냉동보관실','냉장보관실','소모품보관실') then 1.8
    else 0.0
  end,
  case i.location
    when '기기실-1' then 10.0
    when '기기실-2' then 12.4
    when '세포배양실' then 14.6
    when '시약보관실' then 13.6
    when '냉동보관실' then 14.6
    when '냉장보관실' then 12.4
    when '소모품보관실' then 10.0
    when '안전장비함' then 0.0
    else 4.0
  end
from public.items i
where not exists (select 1 from public.virtual_lab_objects v where v.item_id = i.id)
on conflict (scene_object_id) do update set
  room = excluded.room,
  shelf_code = excluded.shelf_code,
  shelf_row = excluded.shelf_row,
  shelf_slot = excluded.shelf_slot,
  location_detail = excluded.location_detail,
  nav_x = excluded.nav_x,
  nav_y = excluded.nav_y,
  enabled = true;

-- 과거 대여·반납실 좌표로 만들어진 일반 바인딩도 최신 9개 구역으로 보정한다.
update public.virtual_lab_objects v
set room = i.location,
    zone_type = case when i.item_type in ('CONSUMABLE','PPE','SAFETY') then 'lab_inventory' else 'restricted_lab' end,
    access_level = 'authorized',
    shelf_code = case i.location
      when '일반실험실' then 'LAB-G00' when '기기실-1' then 'LAB-I01'
      when '기기실-2' then 'LAB-I02' when '세포배양실' then 'LAB-C01'
      when '시약보관실' then 'LAB-R01' when '냉동보관실' then 'LAB-F01'
      when '냉장보관실' then 'LAB-F02' when '소모품보관실' then 'LAB-CON'
      when '안전장비함' then 'LAB-S' end,
    location_detail = i.location || ' 번호표 ' || i.id::text,
    nav_x = case
      when i.location in ('기기실-1','기기실-2','세포배양실') then -1.8
      when i.location in ('냉동보관실','냉장보관실','소모품보관실') then 1.8
      else 0.0 end,
    nav_y = case i.location
      when '기기실-1' then 10.0 when '기기실-2' then 12.4
      when '세포배양실' then 14.6 when '시약보관실' then 13.6
      when '냉동보관실' then 14.6 when '냉장보관실' then 12.4
      when '소모품보관실' then 10.0 when '안전장비함' then 0.0 else 4.0 end
from public.items i
where v.item_id = i.id and v.scene_object_id like 'db-item-%';
