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

  // 세그먼트 탭 바 — 대여/반납 각 흐름 안에서, 누른 단계(1/2/3)의 설명만 펼쳐 보여준다.
  // 흐름마다 탭바가 따로 있으니(.usage-steps 컨테이너 단위로) 이벤트를 그 안에서만 처리한다.
  document.querySelectorAll(".usage-steps").forEach((stepsContainer) => {
    const tabs = stepsContainer.querySelectorAll(".step-tab");
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");

        stepsContainer.querySelectorAll(".step-detail").forEach((detail) => {
          detail.classList.toggle("active", detail.dataset.stepDetail === tab.dataset.step);
        });
      });
    });
  });

  // 푸터의 실시간 시계 — 순수 장식이지만, 고정 문구보다 실제로 시계가 돌아가는
  // 편이 이 페이지가 살아있다는 인상을 준다. 서버 시각이 아니라 접속한 브라우저의
  // 로컬 시각이다(별도 API 호출 없이 그냥 눈으로 보는 용도라 충분함).
  const footerClock = document.getElementById("footerClock");
  if (footerClock) {
    const pad = (n) => String(n).padStart(2, "0");
    const tick = () => {
      const now = new Date();
      footerClock.textContent = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(
        now.getDate()
      )} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    };
    tick();
    setInterval(tick, 1000);
  }
});
