-- LabBot 고정 보관 설비와 내부 물품 계층화
-- 냉동고/냉장고/액체질소 탱크는 대여 대상이 아니며, 실제 보관 물품이 설비를 부모로 참조한다.

begin;

alter table public.items
  add column if not exists is_rentable boolean not null default true,
  add column if not exists storage_parent_item_id bigint references public.items(id) on delete restrict,
  add column if not exists storage_position text;

alter table public.items
  drop constraint if exists items_storage_parent_not_self;
alter table public.items
  add constraint items_storage_parent_not_self
  check (storage_parent_item_id is null or storage_parent_item_id <> id);

create index if not exists items_storage_parent_idx
  on public.items(storage_parent_item_id)
  where storage_parent_item_id is not null;

-- 사람이 들고 나가는 물품이 아니라 연구실에 고정된 보관 설비다.
update public.items
set is_rentable = false,
    storage_parent_item_id = null,
    storage_position = '고정 보관 설비'
where name in (
  '초저온 냉동고 (-80℃)',
  '일반 냉동고 (-20℃)',
  '실험실 냉장고 (4℃)',
  '액체질소 탱크'
);

-- 초저온 보관이 필요한 컴피턴트 세포는 -80℃ 설비에 둔다.
update public.items
set storage_parent_item_id = (
      select id from public.items where name = '초저온 냉동고 (-80℃)' order by id limit 1
    ),
    storage_position = 'Rack A · Cryobox 01 · 1열'
where name = '컴피턴트 세포 (E. coli DH5α)';

-- 나머지 냉동 시약은 -20℃ 냉동고 내부 랙과 박스에 순서대로 배치한다.
with freezer as (
  select id from public.items where name = '일반 냉동고 (-20℃)' order by id limit 1
), ranked as (
  select i.id, row_number() over (order by i.id) as position_no
  from public.items i
  where i.location = '냉동보관실'
    and i.is_rentable = true
    and i.name <> '컴피턴트 세포 (E. coli DH5α)'
)
update public.items i
set storage_parent_item_id = freezer.id,
    storage_position = 'Rack ' || chr(65 + ((ranked.position_no - 1) / 6)::integer)
      || ' · Box ' || lpad((((ranked.position_no - 1) % 6) + 1)::text, 2, '0')
from freezer, ranked
where i.id = ranked.id;

-- 4℃ 보관 물품은 냉장고 내부 선반과 바구니 단위로 배치한다.
with refrigerator as (
  select id from public.items where name = '실험실 냉장고 (4℃)' order by id limit 1
), ranked as (
  select i.id, row_number() over (order by i.id) as position_no
  from public.items i
  where i.location = '냉장보관실'
    and i.is_rentable = true
)
update public.items i
set storage_parent_item_id = refrigerator.id,
    storage_position = ((((ranked.position_no - 1) / 3)::integer) + 1)::text
      || '단 · 바구니 ' || ((((ranked.position_no - 1) % 3)::integer) + 1)::text
from refrigerator, ranked
where i.id = ranked.id;

-- 부모 보관함은 반드시 같은 구역의 대여 불가 고정 설비여야 한다.
create or replace function public.guard_item_storage_parent()
returns trigger as $$
declare
  parent_item public.items%rowtype;
begin
  if new.storage_parent_item_id is null then
    return new;
  end if;

  select * into parent_item from public.items where id = new.storage_parent_item_id;
  if not found or parent_item.is_rentable is distinct from false then
    raise exception 'storage parent must be a fixed non-rentable item';
  end if;
  if parent_item.storage_parent_item_id is not null then
    raise exception 'nested storage fixtures are not allowed';
  end if;
  if parent_item.location <> new.location then
    raise exception 'stored item and storage fixture must share a location';
  end if;
  return new;
end;
$$ language plpgsql security definer set search_path = public;

drop trigger if exists trg_guard_item_storage_parent on public.items;
create trigger trg_guard_item_storage_parent
  before insert or update of storage_parent_item_id, location on public.items
  for each row execute function public.guard_item_storage_parent();

-- 화면 우회나 직접 API 호출로도 고정 설비를 예약할 수 없도록 DB에서 최종 차단한다.
create or replace function public.guard_loan_insert()
returns trigger as $$
declare
  item public.items%rowtype;
begin
  select * into item from public.items where id = new.item_id;
  if item.is_rentable is distinct from true then
    raise exception 'fixed facility is not rentable';
  end if;
  if item.manual_status = 'MAINTENANCE' then
    raise exception 'item under maintenance';
  end if;
  if item.expires_at is not null and item.expires_at < current_date then
    raise exception 'item expired';
  end if;
  if item.available_qty <= 0 then
    raise exception 'no stock available';
  end if;
  return new;
end;
$$ language plpgsql security definer set search_path = public;

commit;

