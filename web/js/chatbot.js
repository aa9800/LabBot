// LabBot - 챗봇 화면 스크립트 (Supabase Edge Function "gemini-chat"을 통해 실제 Gemini 연동)
// 제미나이 API 키는 절대 이 브라우저 코드에 넣지 않는다 — Edge Function 쪽 secret로만 존재한다.
// 지금 등록된 물품 목록(id 포함)을 문맥으로 같이 보내서, 실제 재고에 있는 물품만 추천하게 하고,
// 함수가 돌려준 recommended_item_ids로 "사용하기"/"대여하기" 버튼이 달린 카드를 바로 붙여준다.

document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const messages = document.getElementById("chatMessages");
  const sendBtn = form.querySelector('button[type="submit"]');

  // 대여하기/사용하기 버튼 클릭 시 로그인 세션이 필요해서 미리 받아둔다 —
  // 로그인 안 한 사용자도 챗봇 자체는 그냥 쓸 수 있게 requireLogin으로 막지는 않는다.
  const session = await window.LabBotAuth.getSession();

  // items 테이블 RLS(items_select_all)가 로그인한 사용자만 조회를 허용해서, 비로그인
  // 상태에서는 물품 목록이 항상 빈 채로 내려온다 — 챗봇이 "등록된 물품이 없다"고 답하면
  // 헷갈리니, 애초에 로그인이 필요하다는 걸 화면에 미리 안내한다.
  if (!session) {
    document.getElementById("chatLoginNotice").style.display = "block";
  }

  // 물품 목록(id 포함)을 매번 최신으로 유지 — 대여/사용 직후 재고가 바뀌어도 다음 질문엔 반영되게.
  let itemsById = new Map();
  async function refreshItems() {
    try {
      const items = await window.LabBotItems.searchItems({});
      itemsById = new Map(items.map((it) => [it.id, it]));
      return items;
    } catch (err) {
      console.warn("LabBot: 챗봇 문맥용 물품 목록을 못 가져왔습니다", err);
      return [];
    }
  }
  await refreshItems();

  // 대화 이력 복원 — 새로고침해도 이전 대화가 남아있게(GPT 리뷰 지적).
  // 화면 상단의 고정 인사말은 그대로 두고, 그 뒤에 저장된 대화를 이어 붙인다.
  async function restoreHistory() {
    const history = await window.LabBotChat.fetchChatHistory(session);
    history.forEach((row) => {
      appendMessage(row.content, row.role === "user" ? "user" : "bot");
      if (row.role === "bot" && Array.isArray(row.recommended_item_ids) && row.recommended_item_ids.length > 0) {
        appendRecommendationCards(row.recommended_item_ids);
      }
    });
  }

  function appendMessage(text, sender) {
    const wrapper = document.createElement("div");
    wrapper.className = `chat-message chat-message-${sender}`;

    if (sender === "bot") {
      const avatar = document.createElement("span");
      avatar.className = "chat-avatar";
      avatar.textContent = "AI";
      wrapper.appendChild(avatar);
    }

    const bubble = document.createElement("span");
    bubble.className = "chat-bubble";
    bubble.textContent = text; // DB/사용자 입력이 섞이는 값이라 innerHTML이 아니라 textContent로만 넣는다.

    wrapper.appendChild(bubble);
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
    return { wrapper, bubble };
  }

  // 추천 물품 카드: items.js의 물품 목록 행과 같은 규칙(재고상태/대여가능여부/소모품여부)을 그대로 따른다.
  function appendRecommendationCards(itemIds) {
    const { escapeHtml, STOCK_STATUS_FULL_LABEL, STOCK_STATUS_BADGE_CLASS, computeStockStatus, canRentItem } =
      window.LabBotItems;

    const cardList = document.createElement("div");
    cardList.className = "chat-message chat-message-bot chat-recommend-list";

    itemIds.forEach((id) => {
      const item = itemsById.get(id);
      if (!item) return; // 서버가 추천한 id가 그 사이 삭제됐을 수도 있으니 조용히 건너뜀

      const statusKey = computeStockStatus(item);
      const statusLabel = STOCK_STATUS_FULL_LABEL[statusKey];
      const badgeClass = STOCK_STATUS_BADGE_CLASS[statusKey];
      const rentable = canRentItem(item);
      const consumable = window.LabBotRentals.isConsumable(item);
      // 장비 등은 여기서 바로 대여가 끝나지 않는다 — 예약만 되고, 마이페이지에서 로봇 안내 +
      // QR 스캔을 거쳐야 실제 수령이 확정된다(items.js와 동일한 규칙).
      const actionLabel = consumable ? "사용하기" : "예약하기";

      const card = document.createElement("div");
      card.className = "chat-recommend-card";
      card.innerHTML = `
        <div class="chat-recommend-info">
          <span class="category-tag">${escapeHtml(item.categoryLabel)}</span>
          <span class="chat-recommend-name">${escapeHtml(item.name)}</span>
          <span class="item-row-location">${escapeHtml(item.location)} · 재고 ${item.available_qty}/${item.total_qty}</span>
          <span class="badge ${badgeClass}"><span class="badge-dot"></span>${statusLabel}</span>
        </div>
        ${
          rentable
            ? `<button type="button" class="btn btn-primary btn-sm">${actionLabel}</button>`
            : `<button type="button" class="btn btn-secondary btn-sm" disabled>${consumable ? "재고없음" : "대여불가"}</button>`
        }
      `;

      const button = card.querySelector("button");
      if (rentable) {
        button.addEventListener("click", async () => {
          if (!session) {
            window.LabBotToast.info("로그인 후 이용할 수 있습니다.");
            return;
          }
          button.disabled = true;
          try {
            // 소모품도 예약만 된다 — 마이페이지에서 수량 입력 + QR 스캔을 거쳐야 확정된다.
            await window.LabBotRentals.reserveItem(item, session, "chatbot");
            appendMessage(
              `"${item.name}" 예약되었습니다. 마이페이지에서 로봇 안내를 받아 ${consumable ? "사용" : "수령"}하세요.`,
              "bot"
            );
            await refreshItems();
          } catch (err) {
            window.LabBotToast.error(err.message || "처리 중 오류가 발생했습니다.");
            button.disabled = false;
          }
        });
      }

      cardList.appendChild(card);
    });

    if (cardList.children.length > 0) {
      messages.appendChild(cardList);
      messages.scrollTop = messages.scrollHeight;
    }
  }

  await restoreHistory();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    appendMessage(text, "user");
    input.value = "";
    sendBtn.disabled = true;
    window.LabBotChat.saveChatMessage(session, { role: "user", content: text });

    const { bubble: thinkingBubble } = appendMessage("생각 중...", "bot");

    try {
      const items = [...itemsById.values()].map((it) => ({
        id: it.id,
        name: it.name,
        location: it.location,
        available_qty: it.available_qty,
        total_qty: it.total_qty,
      }));

      const { data, error } = await supabaseClient.functions.invoke("gemini-chat", {
        body: { message: text, items },
      });

      if (error) throw error;
      const reply = data.reply || "죄송해요, 답변을 만들지 못했어요.";
      thinkingBubble.textContent = reply;
      const recommendedIds = Array.isArray(data.recommended_item_ids) ? data.recommended_item_ids : [];

      if (recommendedIds.length > 0) {
        appendRecommendationCards(recommendedIds);
      }
      window.LabBotChat.saveChatMessage(session, { role: "bot", content: reply, recommended_item_ids: recommendedIds });
    } catch (err) {
      console.error("LabBot: 챗봇 응답 실패", err);
      thinkingBubble.textContent = "챗봇 응답을 가져오지 못했어요. 잠시 후 다시 시도해주세요.";
    } finally {
      sendBtn.disabled = false;
      messages.scrollTop = messages.scrollHeight;
    }
  });
});
