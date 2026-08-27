-- LabKeeper 마이그레이션 — 2026-08-27
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 실행하세요.
-- (DDL은 PostgREST로 실행할 수 없어서 여기 모아뒀습니다.)
--
-- 실행 순서는 상관없고, 전부 여러 번 실행해도 안전합니다(IF NOT EXISTS / DROP-CREATE).


-- ─────────────────────────────────────────────────────────────
-- 1. robot_commands: 로봇 IP / 카메라 각도 컬럼 추가
-- ─────────────────────────────────────────────────────────────
-- 왜: 중계기(relay.py)가 로봇의 현재 IP를 여기 기록해서, 웹 Robot Console이
--     어느 주소로 MJPEG 직결 스트림을 붙을지 알아낸다.
-- 증상: 없으면 PATCH가 PGRST204 "Could not find the 'local_ip' column"으로 400 실패.
--       (2026-08-27 중계기 실측에서 확인됨 — 현재 컬럼은 id/mode/speed/turn/updated_at 뿐)

alter table robot_commands add column if not exists local_ip text;
alter table robot_commands add column if not exists cam_pan  integer not null default 90;
alter table robot_commands add column if not exists cam_tilt integer not null default 90;


-- ─────────────────────────────────────────────────────────────
-- 2. restock_subscriptions: UPDATE 정책 추가
-- ─────────────────────────────────────────────────────────────
-- 왜: 재입고 알림을 "읽음" 처리하려면 notified_at을 UPDATE해야 하는데,
--     select/insert/delete 정책만 있어서 RLS에 막힌다.
-- 증상: PostgREST가 에러 대신 "0행 성공"을 돌려주므로 클라이언트는 성공한 줄 안다.
--       결과적으로 우선권 8시간 내내 페이지를 열 때마다 같은 토스트가 반복된다.

drop policy if exists "restock_subscriptions_update_own" on restock_subscriptions;
create policy "restock_subscriptions_update_own" on restock_subscriptions
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());


-- ─────────────────────────────────────────────────────────────
-- 3. damage_reports: UPDATE 정책 추가
-- ─────────────────────────────────────────────────────────────
-- 왜: AI 파손 분석이 실패하면 status가 'pending'에 영원히 갇힌다.
--     select/insert 정책만 있어서 사용자도 관리자도 상태를 못 바꾼다.
-- 증상: 관리자 화면에 "AI 분석 중"으로 박제되어 큐에서 사라지지 않는다.

drop policy if exists "damage_admin_update" on damage_reports;
create policy "damage_admin_update" on damage_reports
  for update using (is_admin()) with check (is_admin());


-- ─────────────────────────────────────────────────────────────
-- 4. guard_loan_self_update: search_path 고정
-- ─────────────────────────────────────────────────────────────
-- 왜: 형제 함수들은 전부 `set search_path = public`을 갖고 있는데 이것만 빠져 있다.
--     이 함수는 "대여 상태 변경은 반드시 검증 RPC를 거쳐야 한다"를 강제하는
--     유일한 방어선이라, search_path 하이재킹에 노출되면 안 된다.
-- 주의: 아래는 함수 본문을 그대로 두고 속성만 바꾸는 방식이라 안전합니다.

alter function public.guard_loan_self_update() set search_path = public;


-- ─────────────────────────────────────────────────────────────
-- 5. refresh_restock_queue: 익명 실행 차단
-- ─────────────────────────────────────────────────────────────
-- 왜: security definer인데 호출자 검사가 없고 PUBLIC 실행이라 익명 사용자도
--     다른 사람의 대기열 승격/만료를 돌릴 수 있다. 멱등이라 피해는 작지만,
--     권한이 호출자보다 넓은 유일한 함수라 좁혀두는 게 맞다.

revoke execute on function public.refresh_restock_queue() from public, anon;
grant  execute on function public.refresh_restock_queue() to authenticated;


-- ─────────────────────────────────────────────────────────────
-- 6. 가상 실험실 (virtual_lab_objects + 확인 RPC 2개)
-- ─────────────────────────────────────────────────────────────
-- 이건 이미 docs/labbot_schema.sql 1646~1770줄에 전부 작성되어 있는데
-- 실제 DB에 실행만 안 된 상태입니다(2026-08-27 실측: PGRST205/PGRST202).
-- 여기 중복해서 붙이면 원본과 어긋날 위험이 있으니,
-- labbot_schema.sql 의 해당 구간을 그대로 복사해서 실행하세요.
--
-- 실행 후 아래로 확인:
--   select count(*) from virtual_lab_objects;
--   select proname from pg_proc where proname like 'confirm_virtual_loan%';


-- ─────────────────────────────────────────────────────────────
-- 확인용 — 1~5번이 제대로 들어갔는지
-- ─────────────────────────────────────────────────────────────
-- select column_name from information_schema.columns
--   where table_name = 'robot_commands' order by column_name;
-- select polname from pg_policy
--   where polrelid in ('restock_subscriptions'::regclass, 'damage_reports'::regclass);
