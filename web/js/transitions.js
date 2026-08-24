// LabBot - 페이지 전환 공통 스크립트
// 내부 링크 클릭 시 살짝 페이드아웃 후 이동하고, 페이지 진입 시 페이드인 처리
// 모든 페이지에서 다른 스크립트보다 먼저 로드되어야 함 (window.LabBotNav 제공)

(function () {
  const TRANSITION_MS = 200;
  let navigating = false;

  function isInternalNavigable(link) {
    const href = link.getAttribute("href");
    if (!href) return false;
    if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:")) return false;
    if (href.startsWith("http://") || href.startsWith("https://") || href.startsWith("//")) return false;
    if (link.target === "_blank") return false;
    if (link.hasAttribute("download")) return false;
    return true;
  }

  function goTo(url) {
    if (navigating) return;
    navigating = true;
    document.body.classList.add("page-leaving");
    window.setTimeout(() => {
      window.location.href = url;
    }, TRANSITION_MS);
  }

  document.addEventListener("DOMContentLoaded", () => {
    requestAnimationFrame(() => {
      document.body.classList.add("page-ready");
    });

    document.addEventListener("click", (e) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;

      const link = e.target.closest("a[href]");
      if (!link || !isInternalNavigable(link)) return;

      e.preventDefault();
      goTo(link.getAttribute("href"));
    });
  });

  // 뒤로가기(bfcache)로 되돌아왔을 때 화면이 안 보이는 채로 남는 것을 방지
  window.addEventListener("pageshow", () => {
    navigating = false;
    document.body.classList.remove("page-leaving");
    document.body.classList.add("page-ready");
  });

  window.LabBotNav = { goTo };
})();
