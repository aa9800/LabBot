-- =============================================================
-- LabBot 물품 데이터 v2 — 생명공학(분자생물학/세포배양) 실험실 기준, 60종
-- (v1의 30종 임시 데이터를 대체. 대여 이력이 있던 물품 1개(HPLC 시스템)는
--  삭제하지 않고 남겨둔 채 새 컬럼 값만 채워 넣었다.)
--
-- 실행 순서: 1) docs/labbot_schema.sql 먼저 실행(테이블 없으면 생성) →
--           2) 이 파일의 ALTER TABLE로 새 컬럼 추가 → 3) 기존 데이터 정리 → 4) 시딩
-- =============================================================

-- 1) items 테이블에 최소 필드만 추가 (이미 있으면 건너뜀 — 안전하게 재실행 가능)
alter table items
  add column if not exists item_type text check (item_type in ('EQUIPMENT','REAGENT','CONSUMABLE','PPE','SAFETY')),
  add column if not exists unit text,
  add column if not exists minimum_qty integer,
  add column if not exists storage_condition text,
  add column if not exists expires_at date,
  add column if not exists manual_status text check (manual_status in ('MAINTENANCE')),  -- null 또는 'MAINTENANCE'만
  add column if not exists notes text default '';

-- manual_status 설명: 관리자가 "직접" 정하는 예외 상태만 저장한다(지금은 점검중뿐).
-- OUT_OF_STOCK/LOW_STOCK/EXPIRED/EXPIRING_SOON/AVAILABLE은 저장하지 않고 매번
-- available_qty/minimum_qty/expires_at 기준으로 새로 계산한다
-- (web/js/items-data.js의 computeStockStatus() 참고 — 계산 로직은 이 한 곳에만 있다).

-- 2) 대여 이력이 없는 기존 물품만 정리 (있는 물품은 FK 제약으로 어차피 삭제 안 됨)
delete from items where id not in (select distinct item_id from loans);

-- 3) 새 물품 60종 시딩 — item_type과 category를 같은 값으로 채워서, 예전 5분류
--    (광학/분리/측정기기...) 대신 장비/시약/소모품/PPE/안전물품으로 통일했다.
--    (실제 INSERT 문은 SQL Editor에서 실행한 것과 동일 — 필요하면 이 파일 그대로 재실행 가능)
insert into items (name, category, location, total_qty, available_qty, item_type, unit, minimum_qty, storage_condition, expires_at, manual_status, notes) values
('형광현미경','EQUIPMENT','기기실-1',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('도립현미경','EQUIPMENT','세포배양실',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('일반 PCR 장비','EQUIPMENT','기기실-1',2,2,'EQUIPMENT','대',1,'기기실',null,null,''),
('Real-time PCR 장비','EQUIPMENT','기기실-1',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('UV-Vis 분광광도계','EQUIPMENT','기기실-1',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('나노드롭','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('마이크로플레이트 리더','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('마이크로 원심분리기','EQUIPMENT','기기실-2',3,3,'EQUIPMENT','대',1,'기기실',null,null,''),
('냉장 원심분리기','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'기기실',null,'MAINTENANCE','발표용: 점검중 시연'),
('전기영동 장치','EQUIPMENT','기기실-2',2,2,'EQUIPMENT','대',1,'기기실',null,null,''),
('Gel documentation system','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('CO2 incubator','EQUIPMENT','세포배양실',2,2,'EQUIPMENT','대',1,'기기실',null,null,''),
('일반 incubator','EQUIPMENT','일반실험실',1,1,'EQUIPMENT','대',1,'일반실험실',null,null,''),
('생물안전작업대','EQUIPMENT','세포배양실',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('Autoclave','EQUIPMENT','일반실험실',1,1,'EQUIPMENT','대',1,'일반실험실',null,null,''),
('Water bath','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'일반실험실',null,null,''),
('Vortex mixer','EQUIPMENT','기기실-2',3,3,'EQUIPMENT','대',1,'일반실험실',null,null,''),
('pH meter','EQUIPMENT','시약보관실',2,2,'EQUIPMENT','대',1,'일반실험실',null,null,''),
('전자저울','EQUIPMENT','기기실-2',2,2,'EQUIPMENT','대',1,'일반실험실',null,null,''),
('마이크로피펫 세트','EQUIPMENT','기기실-2',4,4,'EQUIPMENT','세트',2,'일반실험실',null,null,''),
('PBS','REAGENT','시약보관실',8,8,'REAGENT','병',2,'실온',(current_date + interval '300 days')::date,null,''),
('TAE buffer','REAGENT','시약보관실',6,6,'REAGENT','병',2,'실온',(current_date + interval '300 days')::date,null,''),
('TBE buffer','REAGENT','시약보관실',6,6,'REAGENT','병',2,'실온',(current_date + interval '300 days')::date,null,''),
('Agarose','REAGENT','시약보관실',5,5,'REAGENT','병',1,'실온',(current_date + interval '300 days')::date,null,''),
('DNA ladder','REAGENT','냉동보관실',3,3,'REAGENT','병',1,'냉동',(current_date + interval '20 days')::date,null,'발표용: 유효기간 임박 시연'),
('PCR master mix','REAGENT','냉동보관실',4,4,'REAGENT','병',1,'냉동',(current_date + interval '-10 days')::date,null,'발표용: 유효기간 만료 시연'),
('qPCR master mix','REAGENT','냉동보관실',3,3,'REAGENT','병',1,'냉동',(current_date + interval '200 days')::date,null,''),
('DNA extraction kit','REAGENT','냉장보관실',4,4,'REAGENT','kit',1,'냉장',(current_date + interval '150 days')::date,null,''),
('RNA extraction kit','REAGENT','냉동보관실',3,3,'REAGENT','kit',1,'냉동',(current_date + interval '150 days')::date,null,''),
('Plasmid miniprep kit','REAGENT','시약보관실',4,4,'REAGENT','kit',1,'실온',(current_date + interval '200 days')::date,null,''),
('DMEM','REAGENT','냉장보관실',6,6,'REAGENT','병',2,'냉장',(current_date + interval '120 days')::date,null,''),
('RPMI-1640','REAGENT','냉장보관실',5,5,'REAGENT','병',2,'냉장',(current_date + interval '120 days')::date,null,''),
('Fetal bovine serum','REAGENT','냉동보관실',4,4,'REAGENT','병',1,'냉동',(current_date + interval '180 days')::date,null,''),
('Trypsin-EDTA','REAGENT','냉동보관실',4,4,'REAGENT','병',1,'냉동',(current_date + interval '180 days')::date,null,''),
('DMSO','REAGENT','시약보관실',3,3,'REAGENT','병',1,'실온',(current_date + interval '365 days')::date,null,''),
('10 μL 피펫 팁','CONSUMABLE','소모품보관실',25,25,'CONSUMABLE','박스',5,'실온',null,null,''),
('200 μL 피펫 팁','CONSUMABLE','소모품보관실',25,25,'CONSUMABLE','박스',5,'실온',null,null,''),
('1000 μL 피펫 팁','CONSUMABLE','소모품보관실',20,20,'CONSUMABLE','박스',5,'실온',null,null,''),
('1.5 mL microtube','CONSUMABLE','소모품보관실',30,30,'CONSUMABLE','팩',5,'실온',null,null,''),
('2.0 mL microtube','CONSUMABLE','소모품보관실',25,25,'CONSUMABLE','팩',5,'실온',null,null,''),
('15 mL conical tube','CONSUMABLE','소모품보관실',15,15,'CONSUMABLE','팩',3,'실온',null,null,''),
('50 mL conical tube','CONSUMABLE','소모품보관실',12,12,'CONSUMABLE','팩',3,'실온',null,null,''),
('PCR tube','CONSUMABLE','소모품보관실',20,20,'CONSUMABLE','팩',5,'실온',null,null,''),
('96-well PCR plate','CONSUMABLE','소모품보관실',15,15,'CONSUMABLE','개',3,'실온',null,null,''),
('Petri dish','CONSUMABLE','소모품보관실',15,15,'CONSUMABLE','팩',3,'실온',null,null,''),
('T25 culture flask','CONSUMABLE','세포배양실',20,20,'CONSUMABLE','개',5,'실온',null,null,''),
('T75 culture flask','CONSUMABLE','세포배양실',20,20,'CONSUMABLE','개',5,'실온',null,null,''),
('Cryovial','CONSUMABLE','소모품보관실',30,30,'CONSUMABLE','개',5,'실온',null,null,''),
('Microscope slide','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','박스',2,'실온',null,null,''),
('Cover glass','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','박스',2,'실온',null,null,''),
('실험복','PPE','안전장비함',10,10,'PPE','개',3,'실온',null,null,''),
('니트릴 장갑','PPE','안전장비함',12,12,'PPE','박스',3,'실온',null,null,''),
('보안경','PPE','안전장비함',10,10,'PPE','개',3,'실온',null,null,''),
('Face shield','PPE','안전장비함',6,6,'PPE','개',2,'실온',null,null,''),
('마스크','PPE','안전장비함',8,8,'PPE','박스',2,'실온',null,null,''),
('내열 장갑','PPE','안전장비함',6,6,'PPE','개',2,'실온',null,null,''),
('Biohazard waste bag','SAFETY','안전장비함',8,8,'SAFETY','팩',2,'실온',null,null,''),
('Sharps container','SAFETY','안전장비함',5,5,'SAFETY','개',2,'실온',null,null,''),
('Chemical spill kit','SAFETY','안전장비함',3,3,'SAFETY','개',1,'실온',null,null,''),
('응급처치 키트','SAFETY','안전장비함',2,2,'SAFETY','개',1,'실온',null,null,'');
