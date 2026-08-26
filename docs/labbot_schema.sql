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
  note text default '',
  photo_url text,
  status text not null default 'pending',        -- pending(분석중) / analyzed(완료) / failed(분석실패)
  severity text,                                  -- 제미나이 비전 분석 결과 요약 (경미/보통/심각/즉시교체 등) — 목록에서 빠르게 필터링하려고 별도 컬럼으로 뺌
  ai_result text,                                 -- 제미나이 응답 원문 JSON 문자열 {severity, summary, recommended_action}
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

-- 아래 정책들은 전부 "drop policy if exists" 뒤에 "create policy"를 붙인다 — 이미 정책이
-- 있는 기존 Supabase 프로젝트에서 이 스키마 파일을 처음부터 다시 실행해도 "정책이 이미
-- 있습니다" 에러로 중간에 멈추지 않고 끝까지 재현 가능하게 하기 위해서다(GPT 리뷰가 지적한
-- 문제). 정책 내용 자체는 안 바뀌니 재실행해도 동작은 그대로다.

-- profiles: 본인 것만 보고 고치기, 관리자는 전체 조회
drop policy if exists "profiles_select_own_or_admin" on profiles;
create policy "profiles_select_own_or_admin" on profiles
  for select using (id = auth.uid() or is_admin());
drop policy if exists "profiles_update_own" on profiles;
create policy "profiles_update_own" on profiles
  for update using (id = auth.uid());

-- items: 로그인한 사람은 전부 조회, 등록/수정/삭제는 관리자만
drop policy if exists "items_select_all" on items;
create policy "items_select_all" on items
  for select using (auth.role() = 'authenticated');
drop policy if exists "items_admin_write" on items;
create policy "items_admin_write" on items
  for all using (is_admin()) with check (is_admin());

-- loans: 본인 대여 내역만 보고/만들고, 관리자는 전체 열람·수정
drop policy if exists "loans_select_own_or_admin" on loans;
create policy "loans_select_own_or_admin" on loans
  for select using (user_id = auth.uid() or is_admin());
drop policy if exists "loans_insert_own" on loans;
create policy "loans_insert_own" on loans
  for insert with check (user_id = auth.uid());
drop policy if exists "loans_update_own_or_admin" on loans;
create policy "loans_update_own_or_admin" on loans
  for update using (user_id = auth.uid() or is_admin());

-- audit_sessions / audit_mismatches: 관리자 전용
-- (로봇은 아래 안내처럼 service_role 키로 접근하므로 이 정책과 무관하게 항상 통과됨)
drop policy if exists "audit_admin_only" on audit_sessions;
create policy "audit_admin_only" on audit_sessions
  for all using (is_admin()) with check (is_admin());
drop policy if exists "audit_mismatch_admin_only" on audit_mismatches;
create policy "audit_mismatch_admin_only" on audit_mismatches
  for all using (is_admin()) with check (is_admin());

-- safety_events / action_logs: 로그인하면 읽기 가능(투명성), 쓰기는 관리자만
drop policy if exists "safety_select_all" on safety_events;
create policy "safety_select_all" on safety_events
  for select using (auth.role() = 'authenticated');
drop policy if exists "safety_admin_write" on safety_events;
create policy "safety_admin_write" on safety_events
  for all using (is_admin()) with check (is_admin());
drop policy if exists "action_log_select_all" on action_logs;
create policy "action_log_select_all" on action_logs
  for select using (auth.role() = 'authenticated');
drop policy if exists "action_log_admin_write" on action_logs;
create policy "action_log_admin_write" on action_logs
  for all using (is_admin()) with check (is_admin());

-- damage_reports: 본인이 올린 신고 + 관리자는 전체
drop policy if exists "damage_select_own_or_admin" on damage_reports;
create policy "damage_select_own_or_admin" on damage_reports
  for select using (reported_by = auth.uid() or is_admin());
drop policy if exists "damage_insert_own" on damage_reports;
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
-- 9. 재고실사(audit) — 확인 목록 제출 -> 세션 생성 + 미확인 물품 자동 기록
--    사람이 체크리스트로 확인해서 만든 item_id 목록이든, 나중에 로봇이 스캔해서
--    만든 item_id 목록이든 이 함수 하나만 호출하면 된다 — 로직은 완전히 동일하다.
--    audit_sessions/audit_mismatches는 이미 RLS로 관리자만 쓸 수 있게 막혀 있어서
--    (audit_admin_only, audit_mismatch_admin_only) 이 함수는 security definer가
--    필요 없다 — 호출자 본인이 이미 관리자 권한으로 두 테이블에 쓸 수 있다(로봇은
--    service_role/secret key로 호출하므로 이 RLS 자체를 우회한다).
--
--    2026-08-25 수정(로봇 협업 단계 A/B에서 발견): 원래 코드는
--    `select coalesce(name, '알 수 없음') into performer from profiles where id = auth.uid()`
--    였는데, auth.uid()가 profiles에 아예 없는 행을 가리키면(=매칭되는 행이 0개) SELECT INTO가
--    performer에 아무 값도 대입하지 않아 NULL로 남고, coalesce는 "행이 있는데 name이 NULL일
--    때"만 동작해서 이 경우엔 못 막는다. 로그인 세션이 없는 로봇(service_role 키로 호출,
--    auth.uid()가 NULL)이 그대로 호출하면 `audit_sessions.performed_by`(not null)에 NULL을
--    넣으려다 에러가 난다. 그래서 로봇처럼 auth.uid()가 없는 호출자가 자기 이름을 직접 넘길
--    수 있는 `p_performed_by` 파라미터를 추가했다(안 넘기면 기존 로직대로 동작하되,
--    coalesce를 SELECT 밖으로 빼서 "행 없음"과 "name이 NULL"을 둘 다 안전하게 처리한다).
--    기존 호출(웹 관리자 화면, p_performed_by 안 넘김)은 그대로 동작한다 — 새 파라미터는
--    기본값 null이라 하위호환된다.
-- =============================================================
create or replace function public.run_inventory_audit(
  confirmed_item_ids bigint[],
  p_performed_by text default null
)
returns bigint as $fn$
declare
  new_session_id bigint;
  performer text;
begin
  if p_performed_by is not null and length(trim(p_performed_by)) > 0 then
    -- 로그인 세션이 없어 auth.uid()로 profiles를 조회할 수 없는 호출자(로봇 등)가
    -- 자기 이름을 직접 넘긴 경우 — 그대로 쓴다.
    performer := p_performed_by;
  else
    select name into performer from profiles where id = auth.uid();
    performer := coalesce(performer, '알 수 없음');
  end if;

  insert into audit_sessions (performed_by, started_at, finished_at, scanned_count)
  values (performer, now(), now(), coalesce(array_length(confirmed_item_ids, 1), 0))
  returning id into new_session_id;

  -- 전체 물품 중 확인 목록(confirmed_item_ids)에 없는 것은 전부 미확인으로 자동 기록
  insert into audit_mismatches (session_id, item_id, note)
  select new_session_id, id, '실사 시 미확인'
  from items
  where id <> all(confirmed_item_ids);

  return new_session_id;
end;
$fn$ language plpgsql;

-- =============================================================
-- 10. items 생명공학 물품 필드 보강 — item_type/재고최소치/보관조건/유효기간/점검상태
--     (자세한 시딩 데이터는 docs/labbot_seed_items.sql 참고)
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

-- =============================================================
-- 11. robot_commands + robot-camera Storage — Robot Console(원격조작+카메라) 연동
--     (새 Supabase 프로젝트에서 이 스키마만 실행해도 Robot Console이 바로 동작하도록)
-- =============================================================

-- 로봇이 하나뿐이라 행도 하나뿐(id는 항상 1)이다 — 그냥 "지금 로봇한테 내릴 명령"이라고 보면 된다.
create table if not exists robot_commands (
  id bigint primary key default 1 check (id = 1),
  mode text not null default 'auto' check (mode in ('auto', 'manual')),
  speed float8 not null default 0,
  turn float8 not null default 0,
  updated_at timestamptz not null default now()
);
insert into robot_commands (id) values (1) on conflict (id) do nothing;

alter table robot_commands enable row level security;

drop policy if exists "robot_commands_select_auth" on robot_commands;
create policy "robot_commands_select_auth" on robot_commands
  for select using (auth.role() = 'authenticated');

drop policy if exists "robot_commands_admin_write" on robot_commands;
create policy "robot_commands_admin_write" on robot_commands
  for all using (is_admin()) with check (is_admin());
-- 로봇 자신은 secret key로 접근하므로 위 정책과 무관하게 항상 읽고 쓸 수 있다.

-- 로봇이 몇 초에 한 번씩 올리는 카메라 스냅샷(latest.jpg)을 저장하는 곳.
-- public으로 둬서 웹의 <img> 태그가 별도 인증 없이 바로 불러올 수 있게 했다
-- (카메라가 찍는 건 실험실 내부 풍경이라 민감정보는 아니라고 보고 내린 판단 — 나중에
-- 더 엄격하게 하려면 public=false로 바꾸고 서명된 URL 방식으로 바꾸면 된다).
insert into storage.buckets (id, name, public)
values ('robot-camera', 'robot-camera', true)
on conflict (id) do nothing;

-- 참고: 원격조작 명령에는 항상 updated_at이 갱신되고, 로봇 쪽(robot-sim/webots_project/
-- controllers/labkeeper_controller/labkeeper_controller.py)이 이 값을 확인해서 3초
-- 이상 오래된 수동조작 명령은 "연결 끊김"으로 보고 자동으로 정지한다(dead-man switch).

-- =============================================================
-- 12. 보안 강화 트리거 — RLS만으로는 못 막는 것들을 트리거로 한 번 더 막는다
--     (RLS는 "이 행을 건드릴 수 있냐"만 보고, "어느 컬럼까지 바꿀 수 있냐"는 안 본다)
-- =============================================================

-- profiles: 본인 프로필은 이름 등은 고칠 수 있어야 하지만, role만은 관리자만 바꿀 수 있어야
-- 한다. 정책(policy)만으로는 "이 컬럼은 안 됨"을 표현하기 까다로워서 트리거로 막는다 —
-- 관리자가 아닌데 role을 바꾸려는 시도가 오면, 조용히 원래 값으로 되돌린다.
create or replace function public.prevent_self_role_escalation()
returns trigger as $$
begin
  if new.role is distinct from old.role and not public.is_admin() then
    new.role := old.role;
  end if;
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists trg_prevent_role_escalation on profiles;
create trigger trg_prevent_role_escalation
  before update on profiles
  for each row execute function public.prevent_self_role_escalation();

-- loans: 일반 사용자가 직접 API를 호출하면 item_id/due_at 등을 마음대로 바꾸거나
-- status를 엉뚱하게 되돌릴 수 있었다. "본인 대여를 반납 처리하는 것"만 허용하고,
-- 나머지 컬럼 변경이나 다른 상태 전이는 전부 막는다. 관리자는 이 제한을 받지 않는다.
create or replace function public.guard_loan_self_update()
returns trigger as $$
begin
  if not public.is_admin() then
    if new.item_id is distinct from old.item_id
       or new.user_id is distinct from old.user_id
       or new.due_at is distinct from old.due_at
       or new.borrowed_at is distinct from old.borrowed_at
       or new.source is distinct from old.source then
      raise exception 'not allowed to edit these loan fields';
    end if;
    if old.status <> '대여중' or new.status <> '반납완료' then
      raise exception 'only return transition is allowed';
    end if;
  end if;
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists trg_guard_loan_self_update on loans;
create trigger trg_guard_loan_self_update
  before update on loans
  for each row execute function public.guard_loan_self_update();

-- loans: 대여 신청 자체도 웹 화면(computeStockStatus)만 믿지 않고 DB에서 한 번 더
-- 검사한다 — 점검중/유효기간만료/품절 물품은 직접 API를 호출해도 대여가 안 된다.
create or replace function public.guard_loan_insert()
returns trigger as $$
declare
  item record;
begin
  select * into item from items where id = new.item_id;
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
$$ language plpgsql security definer;

drop trigger if exists trg_guard_loan_insert on loans;
create trigger trg_guard_loan_insert
  before insert on loans
  for each row execute function public.guard_loan_insert();

-- =============================================================
-- 13. damage_reports 보강 + damage-photos Storage — 파손 신고 + 제미나이 비전 자동 분석
--     (기존 damage_reports 테이블에 컬럼만 추가 — 6번 섹션의 create table은 이미 최신 상태로
--     맞춰뒀으니, 이 alter문들은 "6번 섹션이 이미 옛날 버전으로 만들어져 있는 기존 DB"를
--     최신으로 맞추기 위한 것)
-- =============================================================

alter table damage_reports add column if not exists note text default '';
alter table damage_reports add column if not exists status text not null default 'pending';
alter table damage_reports add column if not exists severity text;

-- 사용자가 올린 파손 사진을 저장하는 곳. photo_url을 Edge Function(gemini-damage-assess)이
-- 그대로 제미나이 비전 API에 넘겨야 해서 public으로 뒀다 (robot-camera 버킷과 같은 이유).
insert into storage.buckets (id, name, public)
values ('damage-photos', 'damage-photos', true)
on conflict (id) do nothing;

drop policy if exists "damage_photos_authenticated_upload" on storage.objects;
create policy "damage_photos_authenticated_upload" on storage.objects
  for insert with check (bucket_id = 'damage-photos' and auth.role() = 'authenticated');

-- ai_result/status/severity는 Edge Function이 service role(RLS 우회)로만 갱신한다 —
-- 그래서 일반 사용자용 update 정책은 따로 만들지 않았다(본인이라도 AI 분석결과를
-- 직접 조작할 수 없게).

-- =============================================================
-- 14. Safety 상태변경 + 로그기록 원자적 RPC
--     (기존엔 web/js/safety-data.js에서 update문 + insert문을 따로 두 번 날렸다 —
--     두 번째(로그 기록)가 실패하면 상태만 바뀌고 이력이 안 남는 문제가 있었다.
--     하나의 함수 호출로 묶으면 Postgres가 이 함수 실행 전체를 하나의 트랜잭션으로
--     처리해서, 중간에 에러가 나면 상태변경도 로그기록도 둘 다 롤백된다.)
-- =============================================================

create or replace function public.transition_safety_event(
  p_event_id bigint,
  p_next_status text,
  p_actor text,
  p_note text default ''
)
returns void as $$
begin
  update safety_events
  set
    status = p_next_status,
    resolution_note = case when p_next_status = 'RESOLVED' then coalesce(p_note, '') else resolution_note end,
    resolved_at = case when p_next_status = 'RESOLVED' then now() else resolved_at end
  where id = p_event_id;

  if not found then
    raise exception 'safety_events id %를 찾을 수 없습니다', p_event_id;
  end if;

  insert into action_logs (event_id, actor, action, note)
  values (p_event_id, p_actor, p_next_status, coalesce(p_note, ''));
end;
$$ language plpgsql;
-- security definer를 안 붙였다 — 호출자(로그인한 관리자)의 권한 그대로 실행되어야
-- safety_admin_write/action_log_admin_write RLS 정책(is_admin() 체크)이 그대로 적용된다.

-- =============================================================
-- 15. damage-photos 버킷 용량·MIME 제한 (GPT 리뷰 지적 — 제한이 전혀 없었음)
--     web/js/damage-data.js에서도 같은 제한을 클라이언트에서 먼저 검사하지만, 그건
--     사용자에게 바로 알려주기 위한 것일 뿐이고 실제 방어선은 여기(버킷 설정)다 —
--     클라이언트 코드는 우회 가능해도 버킷 설정은 스토리지 서버가 강제한다.
-- =============================================================

update storage.buckets
set file_size_limit = 5242880, -- 5MB
    allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp', 'image/heic']
where id = 'damage-photos';

-- =============================================================
-- 16. 재고 조정 이력 (GPT 리뷰 지적 — 관리자가 수량을 바꿔도 누가/언제/왜 바꿨는지 기록이
--     전혀 없었음). 관리자가 재고표에서 "저장"을 누를 때마다 이전값→새값을 자동으로
--     한 줄 남긴다. action_logs와 합치지 않고 별도 테이블로 뒀다 — action_logs는
--     safety_events 전용(event_id not null)이라 물품 재고 이력과 성격이 다르다.
-- =============================================================

create table if not exists stock_adjustments (
  id bigint generated always as identity primary key,
  item_id bigint not null references items(id),
  actor text not null,
  previous_available integer not null,
  new_available integer not null,
  previous_total integer not null,
  new_total integer not null,
  note text default '',
  created_at timestamptz not null default now()
);

alter table stock_adjustments enable row level security;

-- 관리자만 보고 쓸 수 있다 — 재고 이력도 items 수정 권한과 같은 선상(관리자 전용).
drop policy if exists "stock_adjustments_admin_only" on stock_adjustments;
create policy "stock_adjustments_admin_only" on stock_adjustments
  for all using (is_admin()) with check (is_admin());

-- GPT 리뷰 지적 — "왜 바꿨는지"가 항상 빈 값이었다. 자유 서술형 대신 5개 사유 중 고르게 해서
-- 나중에 통계 내기도 쉽게 한다("파손·폐기가 이번 달에 몇 건" 같은 질문에 답할 수 있게).
alter table stock_adjustments add column if not exists reason text not null default '기타'
  check (reason in ('신규입고', '사용·소진', '파손·폐기', '실사 수정', '기타'));

-- =============================================================
-- 17. 재고 조정 원자적 RPC (GPT 리뷰 지적 — items UPDATE와 stock_adjustments INSERT가
--     따로 실행돼서, 이력 기록이 실패해도 재고 수정은 그대로 남는 문제가 있었다.
--     Safety RPC(14번 섹션)와 같은 방식으로 하나의 함수 호출로 묶는다.)
-- =============================================================

create or replace function public.adjust_item_stock(
  p_item_id bigint,
  p_new_available integer,
  p_new_total integer,
  p_actor text,
  p_reason text default '기타',
  p_note text default ''
)
returns items as $$
declare
  v_before items;
  v_after items;
begin
  if p_new_available > p_new_total then
    raise exception '대여가능 수량은 총 수량을 넘을 수 없습니다.';
  end if;
  if p_new_available < 0 or p_new_total < 0 then
    raise exception '재고 수량은 0 이상이어야 합니다.';
  end if;

  -- for update로 잠가서, 같은 물품을 두 관리자가 동시에 수정해도 이력의 previous_*
  -- 값이 서로 덮어써지지 않게 한다.
  select * into v_before from items where id = p_item_id for update;
  if not found then
    raise exception 'item id %를 찾을 수 없습니다', p_item_id;
  end if;

  update items
  set available_qty = p_new_available, total_qty = p_new_total
  where id = p_item_id
  returning * into v_after;

  insert into stock_adjustments
    (item_id, actor, previous_available, new_available, previous_total, new_total, reason, note)
  values
    (p_item_id, p_actor, v_before.available_qty, p_new_available, v_before.total_qty, p_new_total, p_reason, p_note);

  return v_after;
end;
$$ language plpgsql;
-- security definer를 안 붙였다 — 호출자(로그인한 관리자)의 권한 그대로 실행되어야
-- items_admin_write/stock_adjustments_admin_only RLS 정책(is_admin() 체크)이 그대로 적용된다.

-- =============================================================
-- 18. 챗봇 대화 이력 저장 (GPT 리뷰 지적 — 새로고침하면 대화가 사라짐)
--     로그인한 사용자별로 본인 대화만 저장/조회. 비로그인 사용자는 여전히 그때그때
--     휘발되는 대화만 가능(원래도 items 조회 자체가 로그인 전제였다).
-- =============================================================

create table if not exists chat_messages (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'bot')),
  content text not null,
  recommended_item_ids integer[] not null default '{}',
  created_at timestamptz not null default now()
);

alter table chat_messages enable row level security;

-- 본인 대화만 읽고 쓸 수 있다 — 다른 사람이 무엇을 물어봤는지 관리자도 볼 필요 없음.
drop policy if exists "chat_messages_own" on chat_messages;
create policy "chat_messages_own" on chat_messages
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create index if not exists chat_messages_user_created_idx on chat_messages(user_id, created_at);

-- =============================================================
-- 19. Storage 비공개 전환 + 서명 URL (GPT 리뷰 지적 — damage-photos/robot-camera가
--     공개 URL이라 주소만 알면 누구나 사진에 접근할 수 있었음)
-- =============================================================

-- damage_reports.photo_url은 "버킷/전체경로/파일명"으로 된 공개 URL 전체를 담고 있었다.
-- 비공개 버킷에서 서명 URL을 매번 새로 발급하려면 경로만 있으면 되므로 photo_path를
-- 새로 두고, 기존 값에서 "/damage-photos/" 뒤쪽 경로만 잘라내 채운다.
alter table damage_reports add column if not exists photo_path text;

update damage_reports
set photo_path = regexp_replace(photo_url, '^.*/damage-photos/', '')
where photo_path is null and photo_url is not null;

update storage.buckets set public = false where id in ('damage-photos', 'robot-camera');

-- damage-photos: 신고 당사자 본인(업로드 경로 첫 폴더 = 본인 user_id) 또는 관리자만 조회 가능.
-- uploadDamagePhoto()가 `${session.id}/파일명` 형태로 올리기 때문에 폴더명으로 본인 여부를 알 수 있다.
drop policy if exists "damage_photos_read_own_or_admin" on storage.objects;
create policy "damage_photos_read_own_or_admin" on storage.objects
  for select using (
    bucket_id = 'damage-photos'
    and (is_admin() or (storage.foldername(name))[1] = auth.uid()::text)
  );

-- robot-camera: 카메라 화면은 관리자 페이지에만 있으므로 관리자만 조회.
-- (업로드는 로봇이 secret key로 하므로 RLS와 무관하게 항상 가능 — robot-commands와 동일)
drop policy if exists "robot_camera_read_admin" on storage.objects;
create policy "robot_camera_read_admin" on storage.objects
  for select using (bucket_id = 'robot-camera' and is_admin());

-- =============================================================
-- 20. 대여를 "예약 → 로봇 안내 → QR 확인" 2단계로 분리 (사용자 요청 — 물품목록에서
--     대여하기를 눌러도 DB에 바로 기록만 되고 실제 확인 절차가 없던 문제)
--     흐름: items.html/챗봇에서 "대여하기" → status='예약중'로 loans 행 생성(재고는 이 시점에
--     -1, 기존 트리거 그대로) → 마이페이지에서 "수령하기" → 로봇 안내 화면 → 물품 QR을
--     스캔하면 confirm_loan_pickup()이 QR을 items.qr_code와 대조해 맞을 때만 '대여중'으로
--     전환. 반납도 마찬가지로 confirm_loan_return()이 QR을 한 번 더 확인한 뒤에만 '반납완료'.
-- =============================================================

-- status 체크 제약에 '예약중' 추가 (기존 제약 이름은 loans_status_check로 확인됨)
alter table loans drop constraint if exists loans_status_check;
alter table loans add constraint loans_status_check
  check (status in ('예약중', '대여중', '반납완료'));

-- 예약 단계에서는 아직 실제로 받아간 게 아니라 반납예정일을 매길 수 없으니 NULL을 허용하고,
-- confirm_loan_pickup()이 실제 수령 시점 기준으로 새로 채운다.
alter table loans alter column due_at drop not null;

-- QR로 실제 수령을 확인한 시각 — null이면 아직 예약만 된 상태(또는 소모품처럼 QR 확인이
-- 필요 없는 경우)라는 뜻으로 관리자 화면 등에서 구분할 때도 쓸 수 있다.
alter table loans add column if not exists qr_confirmed_at timestamptz;

-- guard_loan_self_update()가 기존에는 "대여중 -> 반납완료" 전이만 허용했다 — 이제
-- "예약중 -> 대여중"(픽업 확인) 전이도 허용하고, 그 전이에서는 due_at 변경을 허용한다
-- (반납 전이에서는 여전히 due_at 변경을 막아 대여기간을 사용자가 직접 늘리지 못하게 한다).
create or replace function public.guard_loan_self_update()
returns trigger as $$
begin
  if not public.is_admin() then
    if new.item_id is distinct from old.item_id
       or new.user_id is distinct from old.user_id
       or new.borrowed_at is distinct from old.borrowed_at
       or new.source is distinct from old.source then
      raise exception 'not allowed to edit these loan fields';
    end if;

    if old.status = '대여중' and new.status = '반납완료' then
      if new.due_at is distinct from old.due_at then
        raise exception 'not allowed to edit these loan fields';
      end if;
    elsif old.status = '예약중' and new.status = '대여중' then
      null; -- 이 전이에서는 due_at/qr_confirmed_at 갱신을 허용
    else
      raise exception 'only reservation-pickup or return transitions are allowed';
    end if;
  end if;
  return new;
end;
$$ language plpgsql security definer;

-- 픽업 확인: 본인 예약이 맞는지 + QR이 그 물품 것이 맞는지 서버에서 한 번 더 검증한다
-- (클라이언트 JS 비교만 믿지 않음 — 콘솔로 직접 호출해도 QR 없이는 통과 못 하게).
-- security invoker로 둬서 위 guard 트리거와 loans_update_own_or_admin RLS가 그대로 적용된다.
create or replace function public.confirm_loan_pickup(p_loan_id bigint, p_qr_code text)
returns loans as $$
declare
  v_loan loans;
  v_item items;
begin
  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약입니다.';
  end if;

  select * into v_item from items where id = v_loan.item_id;
  if v_item.qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  update loans
  set status = '대여중',
      due_at = now() + interval '7 days',
      qr_confirmed_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security invoker;

-- 반납 확인: 기존 returnLoan()(직접 UPDATE)과 달리 QR을 서버에서 대조한 뒤에만 반납 처리.
create or replace function public.confirm_loan_return(p_loan_id bigint, p_qr_code text)
returns loans as $$
declare
  v_loan loans;
  v_item items;
begin
  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '대여 내역을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '대여중' then
    raise exception '반납할 수 있는 상태가 아닙니다.';
  end if;

  select * into v_item from items where id = v_loan.item_id;
  if v_item.qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  update loans
  set status = '반납완료',
      returned_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security invoker;

-- =============================================================
-- 21. 소모품 "사용하기"도 예약 → 로봇 안내 → QR 확인 흐름에 맞춘다 (사용자 요청 —
--     "대여하기"와 일관되게 소모품도 실제 확인 후에만 처리되어야 함).
--     소모품은 장비와 달리 "몇 개 썼는지"가 매번 달라서, 예약 시점(reserveItem)에는
--     기존 공용 트리거가 우선 1개만 임시로 차감해두고, 실제 확정(confirm_item_usage)
--     시점에 사용자가 입력한 수량과의 차이만큼만 추가로 반영한다. 소모품은 "반납"
--     개념이 없으므로 예약중에서 바로 반납완료로 간다(대여중 단계를 거치지 않음).
-- =============================================================

alter table loans add column if not exists consumed_qty integer;

-- guard_loan_self_update()에 "예약중 -> 반납완료"(소모품 사용 확정) 전이를 추가로 허용.
create or replace function public.guard_loan_self_update()
returns trigger as $$
begin
  if not public.is_admin() then
    if new.item_id is distinct from old.item_id
       or new.user_id is distinct from old.user_id
       or new.borrowed_at is distinct from old.borrowed_at
       or new.source is distinct from old.source then
      raise exception 'not allowed to edit these loan fields';
    end if;

    if old.status = '대여중' and new.status = '반납완료' then
      if new.due_at is distinct from old.due_at then
        raise exception 'not allowed to edit these loan fields';
      end if;
    elsif old.status = '예약중' and new.status = '대여중' then
      null; -- 장비 픽업 확정: due_at/qr_confirmed_at 갱신 허용
    elsif old.status = '예약중' and new.status = '반납완료' then
      null; -- 소모품 사용 확정: qr_confirmed_at/returned_at/consumed_qty 갱신 허용
    else
      raise exception 'only reservation-pickup, item-usage, or return transitions are allowed';
    end if;
  end if;
  return new;
end;
$$ language plpgsql security definer;

create or replace function public.confirm_item_usage(p_loan_id bigint, p_qr_code text, p_qty integer default 1)
returns loans as $$
declare
  v_loan loans;
  v_item items;
begin
  if p_qty < 1 then
    raise exception '사용 수량은 1개 이상이어야 합니다.';
  end if;

  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약입니다.';
  end if;

  select * into v_item from items where id = v_loan.item_id for update;
  if v_item.qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  -- 예약 시점에 공용 트리거가 이미 1개를 차감해뒀으므로, 실제 사용 수량(p_qty)과의
  -- 차이만큼만 추가로 차감한다(1개보다 적게 쓰면 오히려 돌려줌).
  if v_item.available_qty < (p_qty - 1) then
    raise exception '남은 재고가 부족합니다.';
  end if;
  update items set available_qty = available_qty - (p_qty - 1) where id = v_item.id;

  update loans
  set status = '반납완료',
      qr_confirmed_at = now(),
      returned_at = now(),
      consumed_qty = p_qty
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security invoker;

-- =============================================================
-- 22. 예약 취소 (사용자 요청 — 잘못 예약했을 때 되돌릴 방법이 없었음)
--     Safety 이벤트와 같은 원칙: 행을 지우지 않고 상태를 '취소됨'으로 남긴다
--     (권한 원칙 — "위험 이벤트 삭제 대신 상태 전이와 감사로그를 사용한다"와 동일 기조).
--     예약 시점에 이미 차감된 재고 1개를 취소 시 되돌려야 하는데, items 쓰기는 관리자만
--     허용하는 RLS가 걸려 있어서 이 함수는 security definer로 둔다(loans_increment_stock과
--     동일한 이유). auth.uid()는 definer 안에서도 원래 호출자 그대로라 guard 트리거의
--     권한 검사는 우회되지 않는다.
-- =============================================================

alter table loans drop constraint if exists loans_status_check;
alter table loans add constraint loans_status_check
  check (status in ('예약중', '대여중', '반납완료', '취소됨'));

-- guard_loan_self_update()에 "예약중 -> 취소됨" 전이도 허용.
create or replace function public.guard_loan_self_update()
returns trigger as $$
begin
  if not public.is_admin() then
    if new.item_id is distinct from old.item_id
       or new.user_id is distinct from old.user_id
       or new.borrowed_at is distinct from old.borrowed_at
       or new.source is distinct from old.source then
      raise exception 'not allowed to edit these loan fields';
    end if;

    if old.status = '대여중' and new.status = '반납완료' then
      if new.due_at is distinct from old.due_at then
        raise exception 'not allowed to edit these loan fields';
      end if;
    elsif old.status = '예약중' and new.status = '대여중' then
      null; -- 장비 픽업 확정: due_at/qr_confirmed_at 갱신 허용
    elsif old.status = '예약중' and new.status = '반납완료' then
      null; -- 소모품 사용 확정: qr_confirmed_at/returned_at/consumed_qty 갱신 허용
    elsif old.status = '예약중' and new.status = '취소됨' then
      null; -- 예약 취소: returned_at 갱신 허용
    else
      raise exception 'only reservation-pickup, item-usage, return, or cancel transitions are allowed';
    end if;
  end if;
  return new;
end;
$$ language plpgsql security definer;

-- 본인 예약 또는 관리자만 취소 가능. 이미 픽업/사용/반납이 진행된 건은 취소 대상이 아니다.
create or replace function public.cancel_loan_reservation(p_loan_id bigint)
returns loans as $$
declare
  v_loan loans;
begin
  select * into v_loan from loans
  where id = p_loan_id and (user_id = auth.uid() or is_admin())
  for update;

  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약은 취소할 수 없습니다.';
  end if;

  update items set available_qty = available_qty + 1 where id = v_loan.item_id;

  update loans
  set status = '취소됨',
      returned_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security definer set search_path = public;

-- =============================================================
-- 23. QR 검증 RPC를 거치지 않고 loans 상태를 직접 UPDATE로 바꿀 수 있던 구멍을 막는다
--     (GPT 리뷰 P1-1). 지금까지 guard_loan_self_update()는 "어떤 전이가 허용되는지"만
--     검사했는데, 이건 confirm_loan_pickup() 등 RPC가 하는 것과 똑같은 UPDATE 문이라
--     콘솔이나 REST로 직접 loans를 UPDATE해도 트리거를 그대로 통과했다 — QR 대조나
--     수량 계산 없이 상태만 바뀔 수 있었다는 뜻이다.
--
--     해결: 트랜잭션 로컬 설정(labbot.trusted_transition)을 "신뢰 플래그"로 쓴다. QR/수량
--     검증을 마친 RPC들만 자기 UPDATE 직전에 이 플래그를 켜고, 트리거는 상태 관련 필드가
--     바뀌는데 이 플래그가 없으면 무조건 막는다. PostgREST가 RPC 호출마다 새 트랜잭션을
--     쓰므로, 직접 REST로 UPDATE를 보내는 요청에는 이 플래그가 있을 수 없다.
-- =============================================================

create or replace function public.guard_loan_self_update()
returns trigger as $$
begin
  if not public.is_admin() then
    if new.item_id is distinct from old.item_id
       or new.user_id is distinct from old.user_id
       or new.borrowed_at is distinct from old.borrowed_at
       or new.source is distinct from old.source then
      raise exception 'not allowed to edit these loan fields';
    end if;

    -- status/due_at/qr_confirmed_at/consumed_qty/returned_at은 전부 QR·수량 검증 RPC
    -- (confirm_loan_pickup/confirm_loan_return/confirm_item_usage/cancel_loan_reservation)
    -- 안에서만 바뀔 수 있다. RPC가 검증을 통과한 뒤에만 트랜잭션 로컬로 이 설정을 켜므로,
    -- 신뢰 플래그 없이 이 필드들을 바꾸려는 시도는 여기서 전부 막힌다.
    if (new.status is distinct from old.status
        or new.due_at is distinct from old.due_at
        or new.qr_confirmed_at is distinct from old.qr_confirmed_at
        or new.consumed_qty is distinct from old.consumed_qty
        or new.returned_at is distinct from old.returned_at)
       and coalesce(current_setting('labbot.trusted_transition', true), '') <> 'true' then
      raise exception 'loan status changes must go through the verification RPC';
    end if;
  end if;
  return new;
end;
$$ language plpgsql security definer;

-- 아래 4개 RPC 전부, 검증을 마친 뒤 자기 UPDATE 직전에만 신뢰 플래그를 켠다.

create or replace function public.confirm_loan_pickup(p_loan_id bigint, p_qr_code text)
returns loans as $$
declare
  v_loan loans;
  v_item items;
begin
  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약입니다.';
  end if;

  select * into v_item from items where id = v_loan.item_id;
  if v_item.qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '대여중',
      due_at = now() + interval '7 days',
      qr_confirmed_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security invoker;

create or replace function public.confirm_loan_return(p_loan_id bigint, p_qr_code text)
returns loans as $$
declare
  v_loan loans;
  v_item items;
begin
  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '대여 내역을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '대여중' then
    raise exception '반납할 수 있는 상태가 아닙니다.';
  end if;

  select * into v_item from items where id = v_loan.item_id;
  if v_item.qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '반납완료',
      returned_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security invoker;

create or replace function public.confirm_item_usage(p_loan_id bigint, p_qr_code text, p_qty integer default 1)
returns loans as $$
declare
  v_loan loans;
  v_item items;
begin
  if p_qty < 1 then
    raise exception '사용 수량은 1개 이상이어야 합니다.';
  end if;

  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약입니다.';
  end if;

  select * into v_item from items where id = v_loan.item_id for update;
  if v_item.qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  if v_item.available_qty < (p_qty - 1) then
    raise exception '남은 재고가 부족합니다.';
  end if;
  update items set available_qty = available_qty - (p_qty - 1) where id = v_item.id;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '반납완료',
      qr_confirmed_at = now(),
      returned_at = now(),
      consumed_qty = p_qty
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security invoker;

create or replace function public.cancel_loan_reservation(p_loan_id bigint)
returns loans as $$
declare
  v_loan loans;
begin
  select * into v_loan from loans
  where id = p_loan_id and (user_id = auth.uid() or is_admin())
  for update;

  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약은 취소할 수 없습니다.';
  end if;

  update items set available_qty = available_qty + 1 where id = v_loan.item_id;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '취소됨',
      returned_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security definer set search_path = public;

-- =============================================================
-- 24. QR 코드 비공개화 (GPT Bugbot+Security 리뷰 P0-1) — 지금까지는 items.qr_code를
--     로그인한 사용자 누구나 읽을 수 있어서(items_select_all), 실제로 QR을 촬영하지
--     않고도 콘솔에서 supabaseClient.from('items').select('qr_code')로 값을 그대로
--     가져와 confirm_loan_pickup 등을 호출할 수 있었다 — "물리적으로 QR을 찍어야만
--     확인된다"는 이 프로젝트의 핵심 전제가 깨지는 구멍이었다.
--
--     qr_code를 별도 테이블로 분리하고 관리자만 조회 가능하게 막는다. 검증 RPC들은
--     원래도 서버(DB)에서 값을 대조했으므로 로직은 그대로이고, 이제 그 대조에 쓰는
--     item_qr_codes를 일반 사용자 권한으로는 아예 읽을 수 없다는 점만 강화된다.
-- =============================================================

create table if not exists item_qr_codes (
  item_id bigint primary key references items(id) on delete cascade,
  qr_code text not null unique
);

alter table item_qr_codes enable row level security;

-- 기존 items.qr_code 값을 그대로 옮겨온다(재실행해도 안전 — 이미 있으면 건너뜀).
insert into item_qr_codes (item_id, qr_code)
select id, qr_code from items where qr_code is not null
on conflict (item_id) do nothing;

-- 관리자만 조회 가능 — 일반 사용자는 이 테이블에 대한 select 정책이 아예 없으므로
-- (관리자 정책만 존재) PostgREST로 직접 select를 시도해도 빈 결과만 받는다.
-- insert/update/delete 정책도 만들지 않는다 — 아래 트리거(security definer)만 쓴다.
drop policy if exists "item_qr_codes_admin_select" on item_qr_codes;
create policy "item_qr_codes_admin_select" on item_qr_codes
  for select using (is_admin());

-- items INSERT 시 QR을 새로 발급해 item_qr_codes에 저장한다(generate_item_qr_code()는
-- 7번 섹션에서 이미 만들어둔 함수를 그대로 재사용). identity 컬럼(id)은 BEFORE 트리거
-- 시점에도 이미 채워져 있지만, "행이 실제로 만들어진 뒤에 QR을 발급한다"는 순서를
-- 명확히 하려고 AFTER 트리거로 둔다.
create or replace function public.items_create_qr_code()
returns trigger as $$
begin
  insert into item_qr_codes (item_id, qr_code)
  values (new.id, public.generate_item_qr_code());
  return new;
end;
$$ language plpgsql security definer set search_path = public;

drop trigger if exists trg_items_set_qr_code on items;
drop trigger if exists trg_items_create_qr_code on items;
create trigger trg_items_create_qr_code
  after insert on items
  for each row execute function public.items_create_qr_code();

-- items.qr_code 컬럼은 더 이상 필요 없다 — item_qr_codes로 이전 완료.
alter table items drop column if exists qr_code;

-- 확인 RPC 3개를 QR을 item_qr_codes에서 읽도록 다시 정의하고, security invoker →
-- security definer로 바꾼다. definer가 아니면 안 되는 이유 두 가지:
--   1) item_qr_codes는 관리자만 select 가능하므로, invoker로는 일반 사용자가 호출할 때
--      자기 권한으로 item_qr_codes를 못 읽어서 QR 대조 자체가 항상 실패한다.
--   2) confirm_item_usage()는 실제 사용 수량이 예약 시 임시 차감분(1개)과 다를 때
--      items.available_qty를 UPDATE하는데, items 쓰기는 관리자만 허용하는 RLS
--      (items_admin_write)가 걸려 있어서 invoker로는 일반 사용자가 수량 1개가 아닌
--      사용을 확정할 때마다 권한 오류가 났다(Bugbot 리뷰가 지적한 실제 버그).
create or replace function public.confirm_loan_pickup(p_loan_id bigint, p_qr_code text)
returns loans as $$
declare
  v_loan loans;
  v_qr_code text;
begin
  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약입니다.';
  end if;

  select qr_code into v_qr_code from item_qr_codes where item_id = v_loan.item_id;
  if v_qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '대여중',
      due_at = now() + interval '7 days',
      qr_confirmed_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security definer set search_path = public;

create or replace function public.confirm_loan_return(p_loan_id bigint, p_qr_code text)
returns loans as $$
declare
  v_loan loans;
  v_qr_code text;
begin
  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '대여 내역을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '대여중' then
    raise exception '반납할 수 있는 상태가 아닙니다.';
  end if;

  select qr_code into v_qr_code from item_qr_codes where item_id = v_loan.item_id;
  if v_qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '반납완료',
      returned_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security definer set search_path = public;

create or replace function public.confirm_item_usage(p_loan_id bigint, p_qr_code text, p_qty integer default 1)
returns loans as $$
declare
  v_loan loans;
  v_item items;
  v_qr_code text;
begin
  if p_qty < 1 then
    raise exception '사용 수량은 1개 이상이어야 합니다.';
  end if;

  select * into v_loan from loans where id = p_loan_id and user_id = auth.uid() for update;
  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약입니다.';
  end if;

  select qr_code into v_qr_code from item_qr_codes where item_id = v_loan.item_id;
  if v_qr_code is distinct from p_qr_code then
    raise exception 'QR 코드가 이 물품과 일치하지 않습니다.';
  end if;

  select * into v_item from items where id = v_loan.item_id for update;
  if v_item.available_qty < (p_qty - 1) then
    raise exception '남은 재고가 부족합니다.';
  end if;
  update items set available_qty = available_qty - (p_qty - 1) where id = v_item.id;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '반납완료',
      qr_confirmed_at = now(),
      returned_at = now(),
      consumed_qty = p_qty
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security definer set search_path = public;

-- =============================================================
-- 25. loans 직접 INSERT로 예약 절차 우회 차단 (GPT Bugbot+Security 리뷰 P0-2) —
--     loans_insert_own 정책은 지금까지 user_id만 확인해서, 일반 사용자가
--     status='대여중'/'반납완료'를 직접 INSERT하면 예약(예약중) 단계와 QR 확인을
--     통째로 건너뛸 수 있었다(재고 트리거는 그대로 -1 되어 겉보기엔 정상 작동해서
--     더 위험했다). 새 대여 행은 반드시 "예약중" 상태로만, 다른 진행 필드는 전부
--     비어 있는 채로만 만들 수 있게 강제한다 — 실제 진행은 여전히 검증 RPC를 거쳐야
--     한다. 관리자는 예외(과거 데이터 보정 등에 필요).
-- =============================================================

create or replace function public.guard_loan_self_insert()
returns trigger as $$
begin
  if not public.is_admin() then
    if new.status is distinct from '예약중'
       or new.due_at is not null
       or new.returned_at is not null
       or new.qr_confirmed_at is not null
       or new.consumed_qty is not null then
      raise exception 'new loans must start as 예약중 with no due/return/confirm data';
    end if;
  end if;
  return new;
end;
$$ language plpgsql security definer set search_path = public;

drop trigger if exists trg_guard_loan_self_insert on loans;
create trigger trg_guard_loan_self_insert
  before insert on loans
  for each row execute function public.guard_loan_self_insert();

-- =============================================================
-- 26. P2 보완 3종 (GPT Bugbot+Security 리뷰)
-- =============================================================

-- 26-1. is_admin()에 고정 search_path가 없었다 — security definer 함수에 search_path를
--       고정하지 않으면 호출자가 세션의 search_path를 조작해 다른 스키마의 동명 객체를
--       끼워넣는 공격(search_path 하이재킹)에 이론상 노출된다. 나머지 definer 함수들은
--       이미 set search_path = public이 붙어 있었는데 이 함수만 빠져 있었다.
create or replace function public.is_admin()
returns boolean as $$
  select exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  );
$$ language sql security definer stable set search_path = public;

-- 26-2. damage-photos 업로드 정책이 로그인 여부만 확인하고, 조회 정책과 달리 업로드
--       경로 첫 폴더가 본인 user_id인지는 확인하지 않았다 — 다른 사용자 폴더 경로로
--       사진을 올릴 수 있었다(직접 읽지는 못해도 소유권 경계가 깨짐). 조회 정책과
--       같은 조건을 업로드에도 그대로 건다.
drop policy if exists "damage_photos_authenticated_upload" on storage.objects;
create policy "damage_photos_authenticated_upload" on storage.objects
  for insert with check (
    bucket_id = 'damage-photos'
    and auth.role() = 'authenticated'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- 26-3. cancel_loan_reservation()이 무조건 available_qty + 1을 하는데, 예약 중에
--       관리자가 total_qty를 그보다 낮게 줄여놓으면 items_available_le_total 제약
--       (available_qty <= total_qty)에 걸려 취소 자체가 실패하고 사용자가 예약에
--       발이 묶일 수 있었다. total_qty를 넘지 않는 선까지만 복구하도록 캡을 씌운다.
create or replace function public.cancel_loan_reservation(p_loan_id bigint)
returns loans as $$
declare
  v_loan loans;
begin
  select * into v_loan from loans
  where id = p_loan_id and (user_id = auth.uid() or is_admin())
  for update;

  if not found then
    raise exception '예약을 찾을 수 없습니다.';
  end if;
  if v_loan.status <> '예약중' then
    raise exception '이미 처리된 예약은 취소할 수 없습니다.';
  end if;

  update items
  set available_qty = least(available_qty + 1, total_qty)
  where id = v_loan.item_id;

  perform set_config('labbot.trusted_transition', 'true', true);
  update loans
  set status = '취소됨',
      returned_at = now()
  where id = p_loan_id
  returning * into v_loan;

  return v_loan;
end;
$$ language plpgsql security definer set search_path = public;

-- =============================================================
-- 27. 관리자에게 문의하기 (사용자 요청) — damage_reports와 같은 패턴: 사용자는 본인 글만
--     쓰고 보고, 관리자는 전체를 보고 답변할 수 있다. 별도 알림 없이 마이페이지/관리자
--     페이지에서 각자 확인하는 방식으로 충분하다고 보고 우선 단순하게 만든다.
-- =============================================================

create table if not exists inquiries (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id),
  subject text not null,
  message text not null,
  status text not null default 'open' check (status in ('open', 'answered', 'closed')),
  admin_reply text,
  replied_by uuid references profiles(id),
  replied_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_inquiries_user on inquiries(user_id);

alter table inquiries enable row level security;

-- 본인 문의만 조회/작성, 관리자는 전체 조회
drop policy if exists "inquiries_select_own_or_admin" on inquiries;
create policy "inquiries_select_own_or_admin" on inquiries
  for select using (user_id = auth.uid() or is_admin());

drop policy if exists "inquiries_insert_own" on inquiries;
create policy "inquiries_insert_own" on inquiries
  for insert with check (user_id = auth.uid());

-- 답변 작성(status/admin_reply 등 수정)은 관리자만 — 본인 글이라도 직접 못 고치게 막아서
-- "문의 남겼는데 내용을 조용히 바꿔치기" 같은 위변조를 방지한다(loans 자기수정 방지와 같은 원칙).
drop policy if exists "inquiries_admin_update" on inquiries;
create policy "inquiries_admin_update" on inquiries
  for update using (is_admin()) with check (is_admin());

-- 답변 등록: status/admin_reply/replied_by/replied_at을 한 번에 원자적으로 갱신한다
-- (safety_events의 transition_safety_event()와 같은 이유 — 여러 UPDATE로 나누면 중간에
-- 일부만 반영될 위험이 있다). security definer를 안 붙였다 — 호출자(관리자)의 권한으로
-- 그대로 실행되어야 위 inquiries_admin_update RLS가 적용된다.
create or replace function public.reply_inquiry(
  p_inquiry_id bigint,
  p_reply text
)
returns inquiries as $$
declare
  v_inquiry inquiries;
begin
  update inquiries
  set admin_reply = p_reply,
      status = 'answered',
      replied_by = auth.uid(),
      replied_at = now()
  where id = p_inquiry_id
  returning * into v_inquiry;

  if not found then
    raise exception '문의 id %를 찾을 수 없습니다', p_inquiry_id;
  end if;

  return v_inquiry;
end;
$$ language plpgsql set search_path = public;

-- =============================================================
-- 28. 문의 종결 (자체 디자인 점검 지적) — status에 'closed'가 정의만 되어있고 실제로
--     이 상태로 바꿀 방법이 코드 어디에도 없어서, DB 스키마에만 존재하는 죽은 값이었다.
--     reply_inquiry와 같은 원칙(원자적 갱신, security invoker로 관리자 RLS 그대로 적용).
-- =============================================================

create or replace function public.close_inquiry(
  p_inquiry_id bigint
)
returns inquiries as $$
declare
  v_inquiry inquiries;
begin
  update inquiries
  set status = 'closed'
  where id = p_inquiry_id
  returning * into v_inquiry;

  if not found then
    raise exception '문의 id %를 찾을 수 없습니다', p_inquiry_id;
  end if;

  return v_inquiry;
end;
$$ language plpgsql set search_path = public;

-- =============================================================
-- 29. 재입고 알림 신청 (사용자 요청) — 품절된 물품에 알림을 신청해두면, 재고가 다시
--     들어왔을 때 다음 로그인/페이지 방문 시 토스트로 알려준다. inquiries와 달리 RPC가
--     필요 없다 — 신청·취소·알림 후 소비까지 전부 "본인 행만 건드리는" 단순 CRUD라서
--     여러 단계를 원자적으로 묶을 이유가 없다(reply_inquiry처럼 여러 컬럼을 한 번에
--     바꾸는 경우와 다름). 알림을 띄운 뒤 해당 행을 지우는 방식으로 처리하므로,
--     inquiries 답변 알림이 localStorage에 의존해 다른 브라우저/기기에서 또 뜨던
--     문제(자체 디자인 점검 지적)가 여기서는 애초에 생기지 않는다.
-- =============================================================

create table if not exists restock_subscriptions (
  id bigint generated always as identity primary key,
  item_id bigint not null references items(id) on delete cascade,
  user_id uuid not null references profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (item_id, user_id)
);

create index if not exists idx_restock_subscriptions_user on restock_subscriptions(user_id);
create index if not exists idx_restock_subscriptions_item on restock_subscriptions(item_id);

alter table restock_subscriptions enable row level security;

-- 본인 신청만 보고/걸고/지울 수 있다 — 개인 알림 설정일 뿐이라 관리자도 예외를 둘 이유가 없다.
drop policy if exists "restock_subscriptions_select_own" on restock_subscriptions;
create policy "restock_subscriptions_select_own" on restock_subscriptions
  for select using (user_id = auth.uid());

drop policy if exists "restock_subscriptions_insert_own" on restock_subscriptions;
create policy "restock_subscriptions_insert_own" on restock_subscriptions
  for insert with check (user_id = auth.uid());

drop policy if exists "restock_subscriptions_delete_own" on restock_subscriptions;
create policy "restock_subscriptions_delete_own" on restock_subscriptions
  for delete using (user_id = auth.uid());

-- =============================================================
-- 30. 재입고 알림 → 우선순위 자동예약 대기열로 확장 (사용자 요청 — "신청 순서대로
--     우선권을 주고, 재입고 후 8시간 안에 직접 예약하지 않으면 다음 순위로 넘긴다.
--     알림취소를 누르면 그 즉시 다음 순위로 넘긴다") — 29번 섹션은 "알림만" 줬는데,
--     여기서부터는 누가 지금 예약할 차례인지(우선권)까지 관리한다. 실제 loans 예약은
--     여전히 사용자가 직접 눌러야 생긴다 — 클릭 한 번 없이 로봇 수령 흐름을 강제로
--     시작시키는 건 위험 부담이 커서, "우선권 자동 부여"까지만 자동화하고 예약 자체는
--     기존 reserveItem() 그대로 사용자가 누르게 둔다.
--
--     hold_expires_at: 지금 이 신청자가 우선적으로 예약할 수 있는 마감 시각(null이면
--     아직 대기 중, 아무도 우선권을 안 쓴 상태). notified_at: 우선권을 얻었다는 토스트를
--     이미 보여줬는지(중복 알림 방지 — 신청 시점의 답변 알림과 달리 이 행은 한동안
--     남아있어야 해서 알려준 뒤 지우지 않고 이 컬럼으로만 표시한다).
--
--     이 프로젝트엔 정해진 시각마다 자동 실행되는 배치(cron)가 없다. 그래서 "8시간
--     경과"는 실시간 타이머가 아니라, refresh_restock_queue()를 "누군가 페이지를 열
--     때/신청·취소·예약할 때"마다 호출해서 그 시점 기준으로 지연 판정한다(다른
--     알림들과 같은 원칙). 만료 삭제·다음 순위 승격 둘 다 신청자 본인이 아닌 다른
--     사용자의 행까지 건드려야 해서, 본인 행만 허용하는 RLS로는 안 되고
--     security definer가 필요하다.
-- =============================================================

alter table restock_subscriptions add column if not exists hold_expires_at timestamptz;
alter table restock_subscriptions add column if not exists notified_at timestamptz;

create or replace function public.refresh_restock_queue()
returns void as $$
begin
  -- 우선권을 얻고도 8시간 안에 예약하지 않은 신청은 대기열에서 제거한다
  -- ("다음 우선순위에게 넘어감" — 이 신청자는 다시 줄을 서려면 새로 신청해야 한다).
  delete from restock_subscriptions
  where hold_expires_at is not null and hold_expires_at < now();

  -- 재고가 있는 물품 중 지금 우선권을 쥔 사람이 없으면(위에서 만료분을 이미 지웠으므로
  -- hold_expires_at이 남아있는 행이 없다는 뜻), 가장 오래 기다린 신청자에게 8시간
  -- 우선권을 새로 준다. 물품 하나당 한 명만 승격시킨다(distinct on).
  with promotable as (
    select distinct on (rs.item_id) rs.id
    from restock_subscriptions rs
    join items i on i.id = rs.item_id
    where i.available_qty > 0
      and not exists (
        select 1 from restock_subscriptions h
        where h.item_id = rs.item_id and h.hold_expires_at is not null
      )
    order by rs.item_id, rs.created_at asc
  )
  update restock_subscriptions
  set hold_expires_at = now() + interval '8 hours'
  where id in (select id from promotable);
end;
$$ language plpgsql security definer set search_path = public;
-- =============================================================
-- 31. 관리자용 사용자 관리 (사용자 요청 — "사용자 관리나 미납 몇번 경고 이런 기본적인
--     유저 관리시스템") — 관리자가 전체 사용자를 한눈에 보고(대여 이력, 연체 이력,
--     파손 신고 횟수), 필요하면 직접 경고를 남길 수 있게 한다. 경고는 계정을 자동으로
--     막거나 정지시키지 않는다 — 다른 화면들과 같은 원칙으로, 기록만 남기고 실제 판단은
--     계속 관리자가 사람이 직접 한다.
-- =============================================================

-- 이메일은 profiles에 없고 auth.users에만 있다(회원가입 트리거가 name/role만 복사해서
-- 넣어둔다 — 1번 섹션 참고). 관리자 화면에서만 필요한 값이라 profiles에 컬럼을 추가하는
-- 대신, 관리자만 호출 가능한 RPC로 그때그때 join해서 보여준다.
create or replace function public.admin_list_users()
returns table (
  id uuid,
  name text,
  role text,
  created_at timestamptz,
  email text
) as $$
begin
  if not public.is_admin() then
    raise exception '관리자만 조회할 수 있습니다.';
  end if;

  return query
  select p.id, p.name, p.role, p.created_at, u.email::text
  from public.profiles p
  join auth.users u on u.id = p.id
  order by p.created_at desc;
end;
$$ language plpgsql security definer set search_path = public;

create table if not exists user_warnings (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  reason text not null,
  note text default '',
  created_by uuid references profiles(id),
  created_at timestamptz not null default now()
);

create index if not exists idx_user_warnings_user on user_warnings(user_id);

alter table user_warnings enable row level security;

-- 관리자 전용 내부 메모 성격이라(당사자에게 알림을 보내는 기능은 아직 없음) select/insert/
-- delete 전부 관리자만 허용한다 — safety_events 등 다른 관리자 전용 테이블과 같은 원칙.
drop policy if exists "user_warnings_admin_only" on user_warnings;
create policy "user_warnings_admin_only" on user_warnings
  for all using (is_admin()) with check (is_admin());
