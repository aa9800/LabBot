-- =============================================================
-- LabBot 물품 데이터 v3 — 대학원 분자생물학/세포배양 실험실 규모로 확장 (38종 추가)
--
-- v2(docs/labbot_seed_items.sql)의 60종은 학부 실습실 수준으로 종류가 다소 단순했다.
-- 이 파일은 기존 물품을 지우거나 바꾸지 않고(v2와 달리 DELETE 없음), 실제 대학원
-- 분자생물학/세포배양 랩에 흔히 있지만 빠져 있던 장비·시약·소모품·PPE·안전물품만
-- 추가로 INSERT한다. 실행 후 총 물품 수: 61종(기존) + 38종(신규) = 99종.
--
-- 실행 순서: docs/labbot_schema.sql + docs/labbot_seed_items.sql이 이미 적용된 DB에서
--           이 파일만 그대로 실행하면 된다. 아래 do 블록이 "초저온 냉동고" 존재 여부로
--           이미 실행됐는지 확인하므로(GPT 리뷰 지적 — 재실행 시 중복 INSERT 위험),
--           재실행해도 안전하다(두 번째부터는 조용히 건너뜀).
-- =============================================================

do $$
begin
  if not exists (select 1 from items where name = '초저온 냉동고 (-80℃)') then
    insert into items (name, category, location, total_qty, available_qty, item_type, unit, minimum_qty, storage_condition, expires_at, manual_status, notes) values

-- ---------- 장비(EQUIPMENT) 10종 — 대학원 랩에 실제로 있는데 v2에는 없던 것들 ----------
('초저온 냉동고 (-80℃)','EQUIPMENT','냉동보관실',1,1,'EQUIPMENT','대',1,'냉동',null,null,''),
('일반 냉동고 (-20℃)','EQUIPMENT','냉동보관실',2,2,'EQUIPMENT','대',1,'냉동',null,null,''),
('실험실 냉장고 (4℃)','EQUIPMENT','냉장보관실',2,2,'EQUIPMENT','대',1,'냉장',null,null,''),
('초음파 파쇄기','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('Western blot 전기영동 장치','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('세미드라이 트랜스퍼 장치','EQUIPMENT','기기실-2',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('화학발광 이미징 시스템','EQUIPMENT','기기실-1',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('진탕 배양기','EQUIPMENT','일반실험실',1,1,'EQUIPMENT','대',1,'일반실험실',null,null,''),
('자동 세포계수기','EQUIPMENT','세포배양실',1,1,'EQUIPMENT','대',1,'기기실',null,null,''),
('액체질소 탱크','EQUIPMENT','냉동보관실',1,1,'EQUIPMENT','대',1,'냉동',null,null,''),

-- ---------- 시약(REAGENT) 12종 — 클로닝/발현/Western blot에 필요한데 빠져 있던 것들 ----------
('Ampicillin','REAGENT','냉동보관실',4,4,'REAGENT','병',1,'냉동',(current_date + interval '200 days')::date,null,''),
('Kanamycin','REAGENT','냉동보관실',4,4,'REAGENT','병',1,'냉동',(current_date + interval '200 days')::date,null,''),
('LB broth (분말)','REAGENT','시약보관실',5,5,'REAGENT','병',1,'실온',(current_date + interval '300 days')::date,null,''),
('LB agar (분말)','REAGENT','시약보관실',5,5,'REAGENT','병',1,'실온',(current_date + interval '300 days')::date,null,''),
('컴피턴트 세포 (E. coli DH5α)','REAGENT','냉동보관실',3,3,'REAGENT','튜브',1,'냉동',(current_date + interval '90 days')::date,null,''),
('제한효소 세트','REAGENT','냉동보관실',3,3,'REAGENT','세트',1,'냉동',(current_date + interval '200 days')::date,null,''),
('T4 DNA ligase','REAGENT','냉동보관실',2,2,'REAGENT','병',1,'냉동',(current_date + interval '200 days')::date,null,''),
('Bradford 단백질 정량 키트','REAGENT','냉장보관실',3,3,'REAGENT','kit',1,'냉장',(current_date + interval '150 days')::date,null,''),
('ECL 발광 기질','REAGENT','냉장보관실',3,3,'REAGENT','kit',1,'냉장',(current_date + interval '120 days')::date,null,''),
('BSA (Bovine serum albumin)','REAGENT','냉동보관실',3,3,'REAGENT','병',1,'냉동',(current_date + interval '200 days')::date,null,''),
('무수 에탄올','REAGENT','시약보관실',6,6,'REAGENT','병',2,'실온',(current_date + interval '365 days')::date,null,''),
('이소프로판올','REAGENT','시약보관실',4,4,'REAGENT','병',1,'실온',(current_date + interval '365 days')::date,null,''),

-- ---------- 소모품(CONSUMABLE) 10종 — 필터/멤브레인/배양용기 등 실사용 빈도가 높은 것들 ----------
('실린지 필터 0.22 μm','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','팩',3,'실온',null,null,''),
('실린지 필터 0.45 μm','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','팩',3,'실온',null,null,''),
('PVDF membrane','CONSUMABLE','소모품보관실',5,5,'CONSUMABLE','팩',1,'실온',null,null,''),
('Parafilm','CONSUMABLE','소모품보관실',8,8,'CONSUMABLE','롤',2,'실온',null,null,''),
('Cell strainer 40 μm','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','개',2,'실온',null,null,''),
('Cell scraper','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','개',2,'실온',null,null,''),
('Weighing paper','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','팩',2,'실온',null,null,''),
('SDS-PAGE precast gel','CONSUMABLE','소모품보관실',10,10,'CONSUMABLE','개',3,'실온',null,null,''),
('6-well plate','CONSUMABLE','세포배양실',10,10,'CONSUMABLE','개',2,'실온',null,null,''),
('96-well culture plate','CONSUMABLE','세포배양실',10,10,'CONSUMABLE','개',2,'실온',null,null,''),

-- ---------- PPE 3종 ----------
('방진마스크 (N95급)','PPE','안전장비함',10,10,'PPE','박스',3,'실온',null,null,''),
('화학용 앞치마','PPE','안전장비함',6,6,'PPE','개',2,'실온',null,null,''),
('비닐장갑 (라텍스프리)','PPE','안전장비함',10,10,'PPE','박스',3,'실온',null,null,''),

-- ---------- 안전물품(SAFETY) 3종 ----------
('소화기','SAFETY','안전장비함',2,2,'SAFETY','개',1,'실온',null,null,''),
('방독마스크 (화학물질용)','SAFETY','안전장비함',4,4,'SAFETY','개',1,'실온',null,null,''),
('화상 처치 키트','SAFETY','안전장비함',2,2,'SAFETY','개',1,'실온',null,null,'');
  end if;
end $$;
