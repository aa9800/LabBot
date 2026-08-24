-- =============================================================
-- LabBot 초기 물품 데이터 — 생명공학(분자생물학/세포배양) 실험실 기준
-- 국내외 표준 실험실 규모(대학 연구실~중소 바이오벤처)에서 실제로 쓰는
-- 장비/소모품/안전장비를 카테고리별로 구성했다.
--
-- category는 반드시 web/js/items-data.js의 LAB_CATEGORIES 키와 같아야
-- 화면에 라벨이 정상 표시된다: optical | separation | measurement | consumable | safety
--
-- qr_code는 넣지 않는다 — items 테이블의 트리거(trg_items_set_qr_code)가
-- INSERT 시 자동으로 발급한다 (docs/labbot_schema.sql 7번 섹션).
--
-- location은 실제 실험실 구역명으로 잡아서, 나중에 robot-sim/webots가
-- 이 위치별로 순찰 체크포인트를 자동 생성하는 것과 자연스럽게 연결되게 했다.
-- =============================================================

insert into items (name, category, location, total_qty, available_qty) values
-- 광학기기 (optical)
('형광현미경', 'optical', '기기실-1', 1, 1),
('도립현미경', 'optical', '세포배양실', 1, 1),
('UV-Vis 분광광도계', 'optical', '기기실-1', 1, 1),
('겔 이미징 시스템', 'optical', '기기실-2', 1, 1),
('마이크로플레이트 리더', 'optical', '기기실-2', 1, 1),

-- 분리기기 (separation)
('마이크로 원심분리기', 'separation', '기기실-2', 3, 3),
('초저온 원심분리기', 'separation', '기기실-1', 1, 1),
('젤 전기영동 장치', 'separation', '기기실-2', 2, 2),
('진공 농축기(SpeedVac)', 'separation', '기기실-1', 1, 1),
('HPLC 시스템', 'separation', '기기실-1', 1, 1),

-- 측정기기 (measurement)
('실시간 PCR(qPCR) 기기', 'measurement', '기기실-1', 1, 1),
('나노드롭 분광기', 'measurement', '기기실-2', 1, 1),
('정밀 전자저울', 'measurement', '기기실-2', 2, 2),
('pH 미터', 'measurement', '시약보관실', 2, 2),
('CO2 인큐베이터', 'measurement', '세포배양실', 2, 2),
('워터배스', 'measurement', '기기실-2', 1, 1),
('볼텍스 믹서', 'measurement', '기기실-2', 3, 3),
('마이크로피펫(세트)', 'measurement', '기기실-2', 4, 4),

-- 소모품 (consumable)
('마이크로피펫 팁 (200μL, 박스)', 'consumable', '소모품보관실', 20, 20),
('멸균 마이크로튜브 1.5mL (팩)', 'consumable', '소모품보관실', 30, 30),
('페트리디시 (멸균, 팩)', 'consumable', '소모품보관실', 15, 15),
('세포배양 플라스크 T75', 'consumable', '세포배양실', 25, 25),
('니트릴 장갑 (박스)', 'consumable', '소모품보관실', 12, 12),
('DMEM 세포배양 배지', 'consumable', '저온실(4도)', 8, 8),
('파라필름', 'consumable', '소모품보관실', 6, 6),

-- 안전장비 (safety)
('실험용 고글', 'safety', '안전장비함', 10, 10),
('실험복', 'safety', '안전장비함', 10, 10),
('화학보호장갑 (장갑세트)', 'safety', '안전장비함', 10, 10),
('방진마스크', 'safety', '안전장비함', 15, 15),
('응급처치 키트', 'safety', '안전장비함', 2, 2);
