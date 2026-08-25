// LabBot - 재고 조정 이력 (Supabase stock_adjustments 테이블 연동)
// 관리자가 재고표에서 "저장"을 누를 때마다 이전값→새값을 자동으로 한 줄 남긴다.
// docs/labbot_schema.sql 16번 섹션 참고 — action_logs(safety_events 전용)와는 별개 테이블.

// 재고 수정과 이력 기록을 한 함수로 묶는다 — updateItemStock()과 별도 insert를 admin.js가
// 각자 순서대로 부르게 하지 않고 여기서 같이 처리해서, 호출하는 쪽 코드가 더 단순해진다.
async function adjustItemStock(item, { available_qty, total_qty, actorName, note = "" }) {
  const updated = await window.LabBotItems.updateItemStock(item.id, { available_qty, total_qty });

  // 이력 기록이 실패해도(네트워크 등) 재고 수정 자체는 이미 성공했으니 조용히 콘솔에만 남긴다 —
  // 관리자 작업을 막을 정도로 중요한 실패는 아니다.
  try {
    const { error } = await supabaseClient.from("stock_adjustments").insert({
      item_id: item.id,
      actor: actorName,
      previous_available: item.available_qty,
      new_available: available_qty,
      previous_total: item.total_qty,
      new_total: total_qty,
      note,
    });
    if (error) throw error;
  } catch (err) {
    console.warn("LabBot: 재고 조정 이력 기록 실패(재고 수정 자체는 반영됨)", err);
  }

  return updated;
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
  adjustItemStock,
  fetchStockAdjustments,
};
