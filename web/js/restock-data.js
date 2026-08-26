// LabBot - 재입고 알림 신청 + 우선순위 대기열 데이터 (Supabase restock_subscriptions 테이블 연동)
// docs/labbot_schema.sql 29/30번 섹션 참고. 신청 순서대로 우선권을 주고, 재고가 생기면
// 지금 순서인 사람에게만 8시간짜리 우선권(hold_expires_at)을 부여한다 — 그 안에 직접
// reserveItem()으로 예약해야 하고, 안 하면 refresh_restock_queue()가 다음 순위로 넘긴다.
// 이 프로젝트엔 cron이 없어서 "8시간 경과"는 실시간이 아니라 refreshRestockQueue()를
// 호출하는 시점(페이지 로드/신청/취소/예약)마다 지연 판정된다.
//
// 주의: 우선권은 "먼저 알려준다"는 뜻일 뿐, 실제 재고를 잠가두지는 않는다 — 신청 안 한
// 다른 사용자가 물품목록에서 그 사이 먼저 예약해버리는 것까지 막지는 못한다.

async function refreshRestockQueue() {
  const { error } = await supabaseClient.rpc("refresh_restock_queue");
  if (error) throw error;
}

// 품절된 물품에 재입고 알림을 신청한다(대기열 맨 뒤에 줄을 서는 것과 같다). 이미
// 신청되어 있으면 조용히 무시한다(unique 제약 위반 23505를 성공으로 취급). 신청 직후
// 대기열을 갱신해서, 마침 재고가 남아있는 상태였다면 바로 우선권을 받을 수도 있다.
async function subscribeRestock(itemId, userId) {
  const { error } = await supabaseClient
    .from("restock_subscriptions")
    .insert({ item_id: itemId, user_id: userId });
  if (error && error.code !== "23505") throw error;
  await refreshRestockQueue();
}

// 알림 신청 취소. 우선권을 쥔 상태였다면 이 행이 사라지면서 다음 순위가 곧바로
// 승격되도록 대기열을 갱신한다("알림취소를 누르면 취소 및 다음우선순위에게 넘어감").
async function unsubscribeRestock(itemId, userId) {
  const { error } = await supabaseClient
    .from("restock_subscriptions")
    .delete()
    .eq("item_id", itemId)
    .eq("user_id", userId);
  if (error) throw error;
  await refreshRestockQueue();
}

// 예약(reserveItem)에 성공한 뒤 호출 — 더 이상 대기열에 있을 이유가 없으니 빠져나가고,
// 남은 재고가 있으면 다음 순위에게 바로 우선권을 넘긴다. 애초에 신청한 적이 없어도
// delete가 0행에 대해 에러 없이 끝나므로 그냥 호출해도 안전하다.
async function leaveRestockQueue(itemId, userId) {
  await unsubscribeRestock(itemId, userId);
}

// 물품목록 화면에서 "알림 신청됨" 버튼 상태를 표시하기 위해, 내가 신청해둔 item_id
// 전체를 한 번에 가져온다(물품마다 따로 조회하면 N+1이 된다).
async function fetchMySubscribedItemIds(userId) {
  const { data, error } = await supabaseClient
    .from("restock_subscriptions")
    .select("item_id")
    .eq("user_id", userId);
  if (error) throw error;
  return new Set(data.map((row) => row.item_id));
}

// 마이페이지 "재입고 알림 신청" 목록용 — 내가 신청해둔 전체 목록(대기 중/우선권 보유
// 상태 모두 포함)을 물품명과 함께 가져온다. 화면에 보여줄 때 상태가 최신이어야 하니
// 조회 전에 대기열부터 갱신한다.
async function fetchMySubscriptions(userId) {
  await refreshRestockQueue();

  const { data, error } = await supabaseClient
    .from("restock_subscriptions")
    .select("id, item_id, hold_expires_at, items(id, name, item_type, available_qty)")
    .eq("user_id", userId)
    .order("created_at", { ascending: true });
  if (error) throw error;
  return data;
}

// 내가 지금 우선권을 쥐고 있는(재고 있음 + 8시간 이내) 신청 중, 아직 토스트로 안 알려준
// 것들을 가져온다. 대기열이 이 시점 기준으로 최신인지 먼저 갱신한 뒤 조회한다.
async function fetchReadyRestockNotifications(userId) {
  await refreshRestockQueue();

  const { data, error } = await supabaseClient
    .from("restock_subscriptions")
    .select("id, items(name)")
    .eq("user_id", userId)
    .not("hold_expires_at", "is", null)
    .gt("hold_expires_at", new Date().toISOString())
    .is("notified_at", null);
  if (error) throw error;
  return data;
}

// 알림을 띄운 신청 건은 notified_at만 채우고 행은 남겨둔다 — 행을 지우면 우선권
// 자체가 사라져서, 다음 refresh 때 아직 8시간이 안 지났는데도 다른 사람이 승격되는
// 문제가 생긴다(우선권은 8시간이 지나거나 직접 예약/취소해야만 없어져야 한다).
async function consumeRestockNotification(subscriptionId) {
  const { error } = await supabaseClient
    .from("restock_subscriptions")
    .update({ notified_at: new Date().toISOString() })
    .eq("id", subscriptionId);
  if (error) throw error;
}

window.LabBotRestock = {
  subscribeRestock,
  unsubscribeRestock,
  leaveRestockQueue,
  fetchMySubscribedItemIds,
  fetchMySubscriptions,
  fetchReadyRestockNotifications,
  consumeRestockNotification,
};
