// LabBot - 챗봇 플로팅 팝업 (우하단 💬 버튼)
// chatbot.js와 로직은 거의 같지만, 페이지 이동(chatbot.html) 대신 그 자리에 뜨는 작은
// 창으로 보여준다. chatbot.html은 그대로 남아있으니 필요하면 주소로 바로 들어갈 수
// 있다 — 이 파일은 FAB 버튼의 동작만 "이동"에서 "팝업 토글"로 바꾼다.
// 헤더를 드래그하면 옮길 수 있고, 우하단 모서리를 드래그하면 크기를 바꿀 수 있다.
//
// 사용자 요청("페이지를 넘어가도 닫기 전까지 팝업이 안 사라지게") — 이 사이트는
// SPA가 아니라 페이지마다 완전히 새로 로드되는 구조라, 페이지 전환 순간의 아주 짧은
// 깜빡임(사라졌다 즉시 다시 뜨는 것)까지는 없앨 수 없다는 걸 미리 안내하고 진행했다.
// "열려있음" 여부와 위치·크기를 sessionStorage(탭을 닫으면 사라지는 임시 저장소)에
// 남겨두고, 새 페이지가 열릴 때 그 상태가 있으면 자동으로 다시 띄운다. 대화 내용
// 자체는 원래도 서버(chat_messages)에 저장되니 별도 처리가 필요 없다. ✕ 버튼으로
// 닫으면 이 저장 상태도 같이 지워서, 그 다음부터는 페이지를 넘어가도 안 뜬다.
const CHAT_WIDGET_STATE_KEY = "labbot_chat_widget_open";

function loadWidgetState() {
  try {
    const raw = sessionStorage.getItem(CHAT_WIDGET_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null;
  }
}

function saveWidgetState(panelEl) {
  try {
    sessionStorage.setItem(
      CHAT_WIDGET_STATE_KEY,
      JSON.stringify({
        left: panelEl.style.left || "",
        top: panelEl.style.top || "",
        width: panelEl.style.width || "",
        height: panelEl.style.height || "",
      })
    );
  } catch (err) {
    // 프라이빗 브라우징 등에서 sessionStorage가 막혀 있어도 팝업 자체는 계속 동작해야 하니 조용히 무시.
  }
}

function clearWidgetState() {
  try {
    sessionStorage.removeItem(CHAT_WIDGET_STATE_KEY);
  } catch (err) {
    // 무시 — 애초에 지울 것도 없었다고 보면 된다.
  }
}

// 다른 페이지(또는 더 넓은 화면)에서 저장된 좌표가 지금 화면보다 클 수 있으니,
// 드래그·리사이즈와 같은 기준으로 화면 안에 들어오도록 한 번 더 잡아준다.
function applyWidgetState(panelEl, state) {
  if (!state) return;
  if (state.left && state.top) {
    const left = Math.min(Math.max(parseFloat(state.left) || 0, 0), window.innerWidth - 100);
    const top = Math.min(Math.max(parseFloat(state.top) || 0, 0), window.innerHeight - 60);
    panelEl.style.left = `${left}px`;
    panelEl.style.top = `${top}px`;
    panelEl.style.right = "auto";
    panelEl.style.bottom = "auto";
  }
  if (state.width) panelEl.style.width = state.width;
  if (state.height) panelEl.style.height = state.height;
}

// 헤더를 잡고 끌면 팝업이 따라 움직인다. CSS는 기본적으로 right/bottom으로 위치를
// 잡아두는데, 드래그가 시작되는 순간 그 시점의 실제 좌표를 left/top으로 고정시켜서
// (right/bottom은 auto로 치움) 그 다음부터는 단순히 left/top만 더하면 되게 만든다.
//
// move/up 리스너는 손잡이(handleEl)가 아니라 document에 건다 — 실제로 드래그하면
// 포인터가 그 작은 헤더 영역 밖으로 금방 벗어나는데, handleEl에만 걸어두면 포인터가
// 벗어나는 순간 더 이상 이벤트를 못 받는다. setPointerCapture는 이 문제를 보완해주는
// 표준 방법이지만 실패할 수 있는 API라(예: 이미 해제된 포인터) try/catch로 감싸서,
// 실패해도 document 리스너만으로 드래그가 정상 동작하도록 이중으로 안전하게 만든다.
function makeDraggable(panelEl, handleEl) {
  handleEl.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".chat-widget-close")) return; // 닫기 버튼 클릭까지 드래그로 삼키지 않게
    e.preventDefault();

    const rect = panelEl.getBoundingClientRect();
    panelEl.style.left = `${rect.left}px`;
    panelEl.style.top = `${rect.top}px`;
    panelEl.style.right = "auto";
    panelEl.style.bottom = "auto";

    const startX = e.clientX;
    const startY = e.clientY;
    const startLeft = rect.left;
    const startTop = rect.top;
    panelEl.classList.add("is-dragging");
    try {
      handleEl.setPointerCapture(e.pointerId);
    } catch (err) {
      // 캡처 실패해도 아래 document 리스너로 드래그는 계속 동작한다.
    }

    function onMove(ev) {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      // 화면 밖으로 완전히 사라져서 다시 못 잡는 일이 없게, 항상 좌상단 모서리는
      // 화면 안에 남도록 막는다.
      const maxLeft = window.innerWidth - 100;
      const maxTop = window.innerHeight - 60;
      panelEl.style.left = `${Math.min(Math.max(startLeft + dx, 0), maxLeft)}px`;
      panelEl.style.top = `${Math.min(Math.max(startTop + dy, 0), maxTop)}px`;
    }
    function onUp(ev) {
      try {
        handleEl.releasePointerCapture(ev.pointerId);
      } catch (err) {
        // 캡처가 애초에 안 잡혔을 수도 있으니 실패해도 무시.
      }
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      panelEl.classList.remove("is-dragging");
      saveWidgetState(panelEl); // 옮긴 위치를 저장해서 다음 페이지에서도 같은 자리에 뜨게
    }
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  });
}

// 우하단 모서리를 잡고 끌면 크기가 바뀐다. 드래그와 같은 이유로 좌표를 left/top으로
// 고정한 뒤, 폭/높이만 직접 계산해서 넣는다(CSS의 min/max-width·height가 한계값을
// 최종적으로 한 번 더 막아준다 — 이중 방어). move/up 리스너를 document에 거는 이유와
// setPointerCapture를 try/catch로 감싸는 이유는 makeDraggable과 동일.
function makeResizable(panelEl, handleEl) {
  handleEl.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    e.stopPropagation(); // 헤더까지 이벤트가 번져서 동시에 드래그로 처리되지 않게

    const rect = panelEl.getBoundingClientRect();
    panelEl.style.left = `${rect.left}px`;
    panelEl.style.top = `${rect.top}px`;
    panelEl.style.right = "auto";
    panelEl.style.bottom = "auto";

    const startX = e.clientX;
    const startY = e.clientY;
    const startWidth = rect.width;
    const startHeight = rect.height;
    const maxWidth = window.innerWidth - rect.left - 8;
    const maxHeight = window.innerHeight - rect.top - 8;
    panelEl.classList.add("is-resizing");
    try {
      handleEl.setPointerCapture(e.pointerId);
    } catch (err) {
      // 캡처 실패해도 아래 document 리스너로 리사이즈는 계속 동작한다.
    }

    function onMove(ev) {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      panelEl.style.width = `${Math.min(Math.max(startWidth + dx, 280), maxWidth)}px`;
      panelEl.style.height = `${Math.min(Math.max(startHeight + dy, 320), maxHeight)}px`;
    }
    function onUp(ev) {
      try {
        handleEl.releasePointerCapture(ev.pointerId);
      } catch (err) {
        // 캡처가 애초에 안 잡혔을 수도 있으니 실패해도 무시.
      }
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      panelEl.classList.remove("is-resizing");
      saveWidgetState(panelEl); // 바꾼 크기를 저장해서 다음 페이지에서도 같은 크기로 뜨게
    }
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  const fabBtn = document.getElementById("chatFabBtn");
  if (!fabBtn || !window.LabBotChat) return;

  const session = window.LabBotAuth ? await window.LabBotAuth.getSession() : null;

  let panel = null;
  let itemsById = new Map();
  let historyLoaded = false;

  async function refreshItems() {
    if (!window.LabBotItems) return;
    try {
      const items = await window.LabBotItems.searchItems({});
      itemsById = new Map(items.map((it) => [it.id, it]));
    } catch (err) {
      console.warn("LabBot: 챗봇 팝업 물품 목록을 못 가져왔습니다", err);
    }
  }

  function buildPanel({ autoFocus = true } = {}) {
    const currentPage = window.location.pathname.split("/").pop() || "index.html";
    const el = document.createElement("div");
    el.className = "chat-widget";
    el.innerHTML = `
      <div class="chat-widget-header">
        <span class="chat-widget-title">LabBot 챗봇</span>
        <button type="button" class="chat-widget-close" aria-label="챗봇 닫기">✕</button>
      </div>
      <div class="chat-window">
        <p class="chat-guide">🔎 이용규칙이 궁금하거나, 어떤 실험에 어떤 물품이 필요한지 물어보세요</p>
        ${
          !session
            ? `<p class="chat-login-notice">로그인하지 않아도 챗봇과 대화할 수 있지만, 실제 재고 기반 추천과
                사용하기·대여하기는 <a href="login.html?redirect=${encodeURIComponent(currentPage)}">로그인</a> 후
                이용할 수 있습니다.</p>`
            : ""
        }
        <div class="chat-messages" id="chatWidgetMessages">
          <div class="chat-message chat-message-bot">
            <span class="chat-avatar">AI</span>
            <span class="chat-bubble">안녕하세요! 무엇을 도와드릴까요?</span>
          </div>
        </div>
        <form class="chat-input-bar" id="chatWidgetForm">
          <input type="text" id="chatWidgetInput" placeholder="메시지를 입력하세요" autocomplete="off" />
          <button type="submit" class="btn btn-primary">전송</button>
        </form>
      </div>
      <div class="chat-widget-resize" aria-hidden="true">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M11 5L5 11M11 9L9 11" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
      </div>
    `;
    document.body.appendChild(el);
    applyWidgetState(el, loadWidgetState()); // 다른 페이지에서 옮겨/키워놨다면 그 위치·크기로
    saveWidgetState(el); // "열려있음" 자체를 기록 — 다음 페이지에서도 자동으로 다시 뜨도록

    makeDraggable(el, el.querySelector(".chat-widget-header"));
    makeResizable(el, el.querySelector(".chat-widget-resize"));

    const messagesEl = el.querySelector("#chatWidgetMessages");
    const form = el.querySelector("#chatWidgetForm");
    const input = el.querySelector("#chatWidgetInput");
    const sendBtn = form.querySelector('button[type="submit"]');

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
      messagesEl.appendChild(wrapper);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return { wrapper, bubble };
    }

    // 추천 물품 카드 — chatbot.js와 동일한 규칙(재고상태/대여가능여부/소모품여부)을 그대로 따른다.
    function appendRecommendationCards(itemIds) {
      if (!window.LabBotItems) return;
      const { escapeHtml, STOCK_STATUS_FULL_LABEL, STOCK_STATUS_BADGE_CLASS, computeStockStatus, canRentItem } =
        window.LabBotItems;

      const cardList = document.createElement("div");
      cardList.className = "chat-message chat-message-bot chat-recommend-list";

      itemIds.forEach((id) => {
        const item = itemsById.get(id);
        if (!item) return;

        const statusKey = computeStockStatus(item);
        const statusLabel = STOCK_STATUS_FULL_LABEL[statusKey];
        const badgeClass = STOCK_STATUS_BADGE_CLASS[statusKey];
        const rentable = canRentItem(item);
        const consumable = window.LabBotRentals ? window.LabBotRentals.isConsumable(item) : false;
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
            if (!session || !window.LabBotRentals) {
              window.LabBotToast.info("로그인 후 이용할 수 있습니다.");
              return;
            }
            button.disabled = true;
            try {
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
        messagesEl.appendChild(cardList);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    }

    async function restoreHistory() {
      if (historyLoaded) return;
      historyLoaded = true;
      const history = await window.LabBotChat.fetchChatHistory(session);
      history.forEach((row) => {
        appendMessage(row.content, row.role === "user" ? "user" : "bot");
        if (row.role === "bot" && Array.isArray(row.recommended_item_ids) && row.recommended_item_ids.length > 0) {
          appendRecommendationCards(row.recommended_item_ids);
        }
      });
    }

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
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    });

    restoreHistory();
    // 사용자가 직접 버튼을 눌러서 열 때만 입력창에 포커스를 준다 — 다른 페이지로
    // 넘어가서 자동으로 다시 뜰 때까지 포커스를 뺏으면, 페이지를 보자마자 엉뚱한
    // 곳에 타이핑될 수 있다.
    if (autoFocus) input.focus();

    return el;
  }

  function closePanel() {
    if (!panel) return;
    panel.remove();
    panel = null;
    // 패널을 지우면 대화 DOM도 같이 사라지므로 "이미 불러왔다" 표시도 풀어야 한다.
    // 안 풀면 다시 열었을 때 restoreHistory()가 early return 해서 인사말만 남고
    // 서버에 저장된 대화가 안 보인다.
    historyLoaded = false;
    document.removeEventListener("keydown", onKeydown);
    clearWidgetState(); // 직접 닫았으니 다음 페이지부터는 자동으로 다시 뜨지 않게
  }

  function onKeydown(e) {
    if (e.key === "Escape") closePanel();
  }

  async function openPanel(opts) {
    await refreshItems();
    panel = buildPanel(opts);
    document.addEventListener("keydown", onKeydown);
    panel.querySelector(".chat-widget-close").addEventListener("click", closePanel);
  }

  // 이전 페이지에서 열어둔 채로 넘어왔으면(닫지 않았으면) 자동으로 다시 띄운다.
  if (loadWidgetState()) {
    openPanel({ autoFocus: false });
  }

  fabBtn.addEventListener("click", () => {
    if (panel) {
      closePanel();
    } else {
      openPanel();
    }
  });
});
