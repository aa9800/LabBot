-- 예약한 사람이 자기 물품의 QR을 볼 수 있게 한다
-- ===========================================================================
--
-- 왜 필요한가
-- ----------
-- item_qr_codes 는 지금 관리자만 읽을 수 있다. 물품에 QR 라벨이 붙어 있고
-- 사람이 그 라벨을 로봇에 보여주는 흐름을 전제한 설계였다. 라벨이 실물에
-- 있으니 시스템이 값을 알려줄 이유가 없었다.
--
-- 그런데 실제 운영은 그렇지 않다. 라벨을 아직 못 붙였고, 사용자는 웹에 뜬
-- QR을 로봇 카메라에 보여줘서 대여를 확정한다. 값을 못 보면 대여 자체가
-- 불가능하다.
--
-- 그렇다고 전부 열면 안 된다. QR 하나면 그 물품의 수령이 확정되므로, 아무나
-- 읽을 수 있으면 남의 예약을 가로챌 수 있다.
--
-- 그래서 "자기가 예약했고 아직 안 끝난 건"의 물품에 한해서만 연다. 예약이
-- 없으면 못 보고, 반납이 끝나면 다시 못 본다.

drop policy if exists "item_qr_codes_borrower_select" on item_qr_codes;
create policy "item_qr_codes_borrower_select" on item_qr_codes
  for select using (
    exists (
      select 1
      from loans
      where loans.item_id = item_qr_codes.item_id
        and loans.user_id = auth.uid()
        -- 진행 중인 건만. 취소·반납완료 건으로는 다시 못 본다.
        and loans.status in ('예약중', '대여중')
    )
  );

-- 관리자 정책은 그대로 둔다. 둘 중 하나만 만족하면 읽을 수 있다(정책은 OR).
-- 관리자는 라벨을 인쇄하거나 문제를 확인할 때 전체를 봐야 한다.

-- 확인용
--   select item_id, qr_code from item_qr_codes;
--     -> 관리자: 전체
--     -> 일반 사용자: 자기가 예약중/대여중인 물품만
--     -> 로그인 안 함: 0건
