// LabBot - 챗봇 화면 스크립트 (Supabase Edge Function "gemini-chat"을 통해 실제 Gemini 연동)
// 제미나이 API 키는 절대 이 브라우저 코드에 넣지 않는다 — Edge Function 쪽 secret로만 존재한다.
// 여기서는 지금 등록된 물품 목록을 문맥으로 같이 보내서, 실제 재고에 있는 물품만 추천하게 한다.

document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const messages = document.getElementById("chatMessages");
  const sendBtn = form.querySelector('button[type="submit"]');

  // 물품 목록을 "이름(위치, 대여가능X/총Y)" 형식의 짧은 텍스트로 만들어 챗봇에게 문맥으로 준다.
  // 실패해도(로그인 안 했거나 네트워크 오류) 챗봇 자체는 계속 동작해야 한다.
  let itemContext = "";
  try {
    const items = await window.LabBotItems.searchItems({});
    itemContext = items
      .map((it) => `${it.name}(${it.location}, 대여가능 ${it.available_qty}/${it.total_qty})`)
      .join(", ");
  } catch (err) {
    console.warn("LabBot: 챗봇 문맥용 물품 목록을 못 가져왔습니다", err);
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
    return bubble;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    appendMessage(text, "user");
    input.value = "";
    sendBtn.disabled = true;

    const thinkingBubble = appendMessage("생각 중...", "bot");

    try {
      const { data, error } = await supabaseClient.functions.invoke("gemini-chat", {
        body: { message: text, itemContext },
      });

      if (error) throw error;
      thinkingBubble.textContent = data.reply || "죄송해요, 답변을 만들지 못했어요.";
    } catch (err) {
      console.error("LabBot: 챗봇 응답 실패", err);
      thinkingBubble.textContent = "챗봇 응답을 가져오지 못했어요. 잠시 후 다시 시도해주세요.";
    } finally {
      sendBtn.disabled = false;
      messages.scrollTop = messages.scrollHeight;
    }
  });
});
