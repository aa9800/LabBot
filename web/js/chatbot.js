// LabBot - 챗봇 화면 스크립트
// TODO: Gemini API 연결 후, 사용자 입력을 실제 모델에 전달하고 응답을 받아오는 로직으로 교체할 것
// TODO: 이전 대화 이력 저장/불러오기 (Supabase 연동)

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const messages = document.getElementById("chatMessages");

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    appendMessage(text, "user");
    input.value = "";

    // TODO: 실제 AI 챗봇 응답으로 교체
    appendMessage("(챗봇 응답 자리 - 추후 Gemini API 연결)", "bot");
  });

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
    bubble.textContent = text;

    wrapper.appendChild(bubble);
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
  }
});
