// LabBot - 홈 화면 스크립트
// 히어로의 기본(비로그인) 버튼은 "물품 목록 보기"인데, 로그인 안 한 사람이 눌러봤자
// items.html에서 다시 로그인 페이지로 튕겨나가므로, 로그인 여부를 확인해서
// 비로그인 상태면 "회원가입"으로 바꿔준다. 로그인 상태면 원래대로 물품목록으로 둔다.
document.addEventListener("DOMContentLoaded", async () => {
  const primaryBtn = document.getElementById("heroPrimaryAction");
  if (primaryBtn && window.LabBotAuth) {
    const session = await window.LabBotAuth.getSession();
    if (!session) {
      primaryBtn.textContent = "회원가입";
      primaryBtn.setAttribute("href", "signup.html");
    }
  }

  // 이용 방법 — "대여"/"반납" 버튼으로 각자 다른 3단계 흐름만 보여준다.
  const usageToggleButtons = document.querySelectorAll(".usage-toggle-btn");
  usageToggleButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      usageToggleButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      document.querySelectorAll(".usage-steps").forEach((steps) => {
        steps.classList.toggle("active", steps.id === `usageSteps-${btn.dataset.usage}`);
      });
    });
  });
});
