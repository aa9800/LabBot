// LabBot - 재고 조정 이력 (Supabase stock_adjustments 테이블 연동)
// 관리자가 재고표에서 "저장"을 누를 때마다 이전값→새값을 자동으로 한 줄 남긴다.
// docs/labbot_schema.sql 16~17번 섹션 참고 — action_logs(safety_events 전용)와는 별개 테이블.

// 재고를 몇 가지 이유 중 하나로 분류해서 남긴다 — "왜 바꿨는지"를 자유서술형으로 두면
// 항상 빈 값이 되기 쉬워서(실제로 그랬다), 선택지로 강제하고 "기타"일 때만 메모를 받는다.
const STOCK_ADJUSTMENT_REASONS = ["신규입고", "사용·소진", "파손·폐기", "실사 수정", "기타"];

// 재고 수정과 이력 기록을 DB 함수(adjust_item_stock) 하나로 묶는다 — 예전엔 update문+insert문을
// 따로 두 번 날려서, 이력 기록이 실패해도 재고 수정은 그대로 남는 문제가 있었다(GPT 리뷰 지적).
// 이제는 하나의 트랜잭션이라 둘 다 성공하거나 둘 다 롤백된다.
async function adjustItemStock(item, { available_qty, total_qty, actorName, reason = "기타", note = "" }) {
  const { data, error } = await supabaseClient.rpc("adjust_item_stock", {
    p_item_id: item.id,
    p_new_available: available_qty,
    p_new_total: total_qty,
    p_actor: actorName,
    p_reason: reason,
    p_note: note,
  });
  if (error) throw error;
  return { ...data, categoryLabel: window.LabBotItems.categoryLabelOf(data.category) };
}

async function fetchStockAdjustments(itemId) {
  const { data, error } = await supabaseClient
    .from("stock_adjustments")
    .select("*")
    .eq("item_id", itemId)
    .order("created_at", { ascending: false });

  if (error) throw error;
  return data;
}

window.LabBotStockAdjustments = {
  STOCK_ADJUSTMENT_REASONS,
  adjustItemStock,
  fetchStockAdjustments,
};
