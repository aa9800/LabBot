// LabBot - 공용 토스트 알림 (alert() 대체)
// 화면을 막는 브라우저 기본 alert() 대신, 우상단에 잠깐 떴다 사라지는 알림.
// 다른 스크립트보다 먼저 로드되어야 함 (window.LabBotToast 제공). 클릭하면 바로 닫힌다.

(function () {
  const CONTAINER_ID = "labbotToastContainer";
  const DURATION_MS = 3200;

  function ensureContainer() {
    let el = document.getElementById(CONTAINER_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = CONTAINER_ID;
      el.className = "toast-container";
      document.body.appendChild(el);
    }
    return el;
  }

  function show(message, type) {
    const container = ensureContainer();
    const toast = document.createElement("div");
    toast.className = `toast toast-${type || "info"}`;
    toast.textContent = message;
    container.appendChild(toast);

    // 추가 직후 바로 클래스를 주면 트랜지션이 안 먹어서(같은 프레임), 한 틱 뒤에 준다.
    // requestAnimationFrame은 탭이 백그라운드에 있으면 늦게 불릴 수 있어 setTimeout을 쓴다.
    setTimeout(() => toast.classList.add("toast-visible"), 20);

    let dismissed = false;
    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      toast.classList.remove("toast-visible");
      toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    }

    const timer = setTimeout(dismiss, DURATION_MS);
    toast.addEventListener("click", () => {
      clearTimeout(timer);
      dismiss();
    });
  }

  window.LabBotToast = {
    show,
    success: (message) => show(message, "success"),
    error: (message) => show(message, "error"),
    info: (message) => show(message, "info"),
  };
})();
