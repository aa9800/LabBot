-- =============================================================
-- LabBot Supabase 스키마
-- LabKeeper에서 검증한 데이터 모델을 그대로 옮긴 것.
-- (자세한 설명은 LabBot_기능요구사항.html 02장 참고)
--
-- 사용법: Supabase 대시보드 > SQL Editor에 이 파일 전체를 붙여넣고 Run.
-- 순서대로 실행되므로 통째로 한 번에 돌리면 됩니다.
-- =============================================================

-- -------------------------------------------------------------
-- 1. profiles — auth.users에 이름/역할(role)을 붙이는 테이블
-- -------------------------------------------------------------
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  name text not null,
  role text not null default 'user' check (role in ('user', 'admin')),
  created_at timestamptz not null default now()
);

-- 회원가입(Supabase Auth) 시 profiles 행을 자동으로 만들어주는 트리거
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, name, role)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'name', new.email), 'user');
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- -------------------------------------------------------------
-- 2. items — 물품
-- -------------------------------------------------------------
create table if not exists items (
  id bigint generated always as identity primary key,
  name text not null,
  category text not null,
  location text not null,
  qr_code text not null unique,
  total_qty integer not null default 1 check (total_qty >= 0),
  available_qty integer not null default 1 check (available_qty >= 0),
  status text not null default '정상' check (status in ('정상', '고장', '폐기')),
  created_at timestamptz not null default now()
);

-- -------------------------------------------------------------
-- 3. loans — 대여 · 반납 (핵심: 지금 LabBot의 "재고 -1/+1 토글"을 대체)
-- -------------------------------------------------------------
create table if not exists loans (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id),
  item_id bigint not null references items(id),
  borrowed_at timestamptz not null default now(),
  due_at timestamptz not null,
  returned_at timestamptz,
  status text not null default '대여중' check (status in ('대여중', '반납완료')),
  source text not null default 'manual' check (source in ('manual', 'chatbot'))
  -- source: 물품목록에서 직접 신청('manual') vs 챗봇 추천 → 장바구니 → 일괄대여('chatbot')
);

create index if not exists idx_loans_user on loans(user_id);
create index if not exists idx_loans_item on loans(item_id);

-- -------------------------------------------------------------
-- 4. audit_sessions / audit_mismatches — 실사
-- -------------------------------------------------------------
create table if not exists audit_sessions (
  id bigint generated always as identity primary key,
  performed_by text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  scanned_count integer not null default 0
);

create table if not exists audit_mismatches (
  id bigint generated always as identity primary key,
  session_id bigint not null references audit_sessions(id) on delete cascade,
  item_id bigint not null references items(id),
  note text default ''
);

-- -------------------------------------------------------------
-- 5. safety_events / action_logs — 안전 이벤트 폐쇄루프
-- -------------------------------------------------------------
create table if not exists safety_events (
  id bigint generated always as identity primary key,
  rule_id text not null,
  severity text not null default 'MEDIUM' check (severity in ('HIGH', 'MEDIUM', 'LOW')),
  status text not null default 'NEEDS_REVIEW'
    check (status in ('NEEDS_REVIEW', 'OPEN', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED', 'FALSE_POSITIVE')),
  source text not null default 'manual',
  note text default '',
  detected_at timestamptz not null default now(),
  assignee_id uuid references profiles(id),
  due_at timestamptz,
  resolution_note text default '',
  resolved_at timestamptz
);

create table if not exists action_logs (
  id bigint generated always as identity primary key,
  event_id bigint not null references safety_events(id) on delete cascade,
  actor text not null,
  action text not null,
  note text default '',
  created_at timestamptz not null default now()
);

-- -------------------------------------------------------------
-- 6. damage_reports — 파손 신고 + AI 분석 (LabBot admin.html에 이미 있던 탭)
-- -------------------------------------------------------------
create table if not exists damage_reports (
  id bigint generated always as identity primary key,
  item_id bigint not null references items(id),
  reported_by uuid references profiles(id),
  photo_url text,
  ai_result text,
  created_at timestamptz not null default now()
);

-- =============================================================
-- Row Level Security (RLS)
-- 지금 LabBot처럼 "관리자 계정이 JS에 노출"되는 방식이 아니라,
-- DB 레벨에서 강제하는 방식. RLS를 켜면 정책(policy)이 없는 접근은
-- 기본적으로 전부 막힌다 — 그래서 각 테이블에 필요한 정책만 명시로 열어준다.
-- =============================================================

alter table profiles enable row level security;
alter table items enable row level security;
alter table loans enable row level security;
alter table audit_sessions enable row level security;
alter table audit_mismatches enable row level security;
alter table safety_events enable row level security;
alter table action_logs enable row level security;
alter table damage_reports enable row level security;

-- 관리자인지 확인하는 헬퍼 함수 (정책 여러 곳에서 재사용)
create or replace function public.is_admin()
returns boolean as $$
  select exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  );
$$ language sql security definer stable;

-- profiles: 본인 것만 보고 고치기, 관리자는 전체 조회
create policy "profiles_select_own_or_admin" on profiles
  for select using (id = auth.uid() or is_admin());
create policy "profiles_update_own" on profiles
  for update using (id = auth.uid());

-- items: 로그인한 사람은 전부 조회, 등록/수정/삭제는 관리자만
create policy "items_select_all" on items
  for select using (auth.role() = 'authenticated');
create policy "items_admin_write" on items
  for all using (is_admin()) with check (is_admin());

-- loans: 본인 대여 내역만 보고/만들고, 관리자는 전체 열람·수정
create policy "loans_select_own_or_admin" on loans
  for select using (user_id = auth.uid() or is_admin());
create policy "loans_insert_own" on loans
  for insert with check (user_id = auth.uid());
create policy "loans_update_own_or_admin" on loans
  for update using (user_id = auth.uid() or is_admin());

-- audit_sessions / audit_mismatches: 관리자 전용
-- (로봇은 아래 안내처럼 service_role 키로 접근하므로 이 정책과 무관하게 항상 통과됨)
create policy "audit_admin_only" on audit_sessions
  for all using (is_admin()) with check (is_admin());
create policy "audit_mismatch_admin_only" on audit_mismatches
  for all using (is_admin()) with check (is_admin());

-- safety_events / action_logs: 로그인하면 읽기 가능(투명성), 쓰기는 관리자만
create policy "safety_select_all" on safety_events
  for select using (auth.role() = 'authenticated');
create policy "safety_admin_write" on safety_events
  for all using (is_admin()) with check (is_admin());
create policy "action_log_select_all" on action_logs
  for select using (auth.role() = 'authenticated');
create policy "action_log_admin_write" on action_logs
  for all using (is_admin()) with check (is_admin());

-- damage_reports: 본인이 올린 신고 + 관리자는 전체
create policy "damage_select_own_or_admin" on damage_reports
  for select using (reported_by = auth.uid() or is_admin());
create policy "damage_insert_own" on damage_reports
  for insert with check (reported_by = auth.uid());

-- =============================================================
-- 참고: 로봇(robot-sim, 나중에 실물 Raspbot)이 safety_events / audit_sessions에
-- 쓸 때는 브라우저용 anon key가 아니라 Supabase의 "service_role" 키를 쓰면 된다.
-- service_role 키는 RLS를 통째로 우회하므로 위 정책과 무관하게 항상 쓸 수 있다.
-- 단, 이 키는 절대 프론트엔드(JS) 코드에 넣으면 안 되고, 로봇 쪽 서버/스크립트에만 둔다.
-- =============================================================

-- =============================================================
-- 7. items 물품관리 보강 — QR 코드 서버 발급 + 재고 정합성
--    이미 위 CREATE TABLE을 한 번 실행한 프로젝트에도 안전하게 다시 실행 가능.
-- =============================================================

-- qr_code는 클라이언트가 정하지 않는다 — INSERT할 때마다 서버(DB)가 항상 새로 발급한다.
create or replace function public.generate_item_qr_code()
returns text as $$
  select 'LB-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 8));
$$ language sql volatile;

create or replace function public.items_set_qr_code()
returns trigger as $$
begin
  new.qr_code := public.generate_item_qr_code();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_items_set_qr_code on items;
create trigger trg_items_set_qr_code
  before insert on items
  for each row execute function public.items_set_qr_code();

-- available_qty는 total_qty를 절대 넘을 수 없다 (등록/수정 어느 경로로 와도 여기서 최종 차단)
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'items_available_le_total'
  ) then
    alter table items
      add constraint items_available_le_total check (available_qty <= total_qty);
  end if;
end $$;

-- 참고: loans.item_id가 items(id)를 참조할 때 ON DELETE를 지정하지 않았으므로
-- (기본값 NO ACTION) 대여 이력이 있는 물품은 삭제 시 DB가 자동으로 막는다
-- (foreign_key_violation, 에러코드 23503). 프론트엔드는 이 에러를 잡아서
-- "대여 이력이 있어 삭제할 수 없습니다" 안내만 보여주면 된다 (web/js/items-data.js 참고).

-- =============================================================
-- 8. loans 대여/반납 보강 — 반납예정일 기본값 + 재고 증감 서버 처리
--    이미 위 CREATE TABLE을 한 번 실행한 프로젝트에도 안전하게 다시 실행 가능.
--    "연체"는 여기서 컬럼으로 저장하지 않는다 — 조회 시점에 매번
--    (returned_at is null and now() > due_at)로 계산하는 파생값이다
--    (web/js/rentals.js의 isOverdue 참고).
-- =============================================================

-- due_at을 클라이언트가 안 넘기면 서버가 "오늘 + 7일"을 기본값으로 채운다.
alter table loans alter column due_at set default (now() + interval '7 days');

-- 대여(loans row 생성) 시 해당 물품의 available_qty를 서버가 직접 -1 한다.
-- items.available_qty >= 0 제약(기존 CHECK)이 있어서, 재고가 없는데 동시에
-- 대여가 몰리는 경쟁 상황이 와도 여기서 막히고 loans insert 자체가 롤백된다.
-- security definer 필수: items 쓰기는 관리자만 허용하는 RLS가 걸려 있어서,
-- 일반 사용자 권한으로 트리거가 돌면 이 UPDATE가 조용히 0건 적용되고 만다.
create or replace function public.loans_decrement_stock()
returns trigger as $fn$
begin
  update items set available_qty = available_qty - 1 where id = new.item_id;
  return new;
end;
$fn$ language plpgsql security definer set search_path = public;

drop trigger if exists trg_loans_decrement_stock on loans;
create trigger trg_loans_decrement_stock
  after insert on loans
  for each row execute function public.loans_decrement_stock();

-- 반납(status: 대여중 -> 반납완료) 시 서버가 available_qty를 +1 한다. (역시 security definer 필수)
create or replace function public.loans_increment_stock()
returns trigger as $fn$
begin
  if old.status = '대여중' and new.status = '반납완료' then
    update items set available_qty = available_qty + 1 where id = new.item_id;
  end if;
  return new;
end;
$fn$ language plpgsql security definer set search_path = public;

drop trigger if exists trg_loans_increment_stock on loans;
create trigger trg_loans_increment_stock
  after update on loans
  for each row execute function public.loans_increment_stock();

-- =============================================================
-- 9. items 생명공학 물품 필드 보강 — item_type/재고최소치/보관조건/유효기간/점검상태
--    (자세한 시딩 데이터는 docs/labbot_seed_items.sql 참고)
-- =============================================================

alter table items
  add column if not exists item_type text check (item_type in ('EQUIPMENT','REAGENT','CONSUMABLE','PPE','SAFETY')),
  add column if not exists unit text,
  add column if not exists minimum_qty integer,
  add column if not exists storage_condition text,
  add column if not exists expires_at date,
  add column if not exists manual_status text check (manual_status in ('MAINTENANCE')),
  add column if not exists notes text default '';

-- manual_status: 관리자가 직접 정하는 예외 상태만 저장(null 또는 'MAINTENANCE').
-- OUT_OF_STOCK/LOW_STOCK/EXPIRED/EXPIRING_SOON/AVAILABLE은 저장하지 않고, 매번
-- available_qty/minimum_qty/expires_at 기준으로 새로 계산한다 —
-- web/js/items-data.js의 computeStockStatus()가 유일한 계산 지점이다.
