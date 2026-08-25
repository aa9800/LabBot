// LabBot - 공통 네비게이션 스크립트

document.addEventListener("DOMContentLoaded", async () => {
  const currentPage = document.body.dataset.page;

  document.querySelectorAll(".nav-links a[data-nav]").forEach((link) => {
    if (link.dataset.nav === currentPage) {
      link.classList.add("active");
    }
  });

  const session = window.LabBotAuth ? await window.LabBotAuth.getSession() : null;
  const loginLink = document.querySelector('.nav-links a[data-nav="login"]');
  const mypageLink = document.querySelector('.nav-links a[data-nav="mypage"]');
  const adminLink = document.querySelector('.nav-links a[data-nav="admin"]');

  if (mypageLink) {
    mypageLink.style.display = session ? "inline" : "none";
  }

  // 일반 사용자로 로그인하면 관리자 링크를 숨긴다(비로그인 상태는 그대로 노출 — 관리자가
  // 로그인 전 화면에서도 admin.html로 들어갈 수 있어야 하므로). UI 노출용 편의 기능일 뿐,
  // 실제 접근 차단은 DB의 is_admin() RLS가 담당한다.
  if (adminLink) {
    adminLink.style.display = session && session.role !== "admin" ? "none" : "inline";
  }

  if (loginLink && session) {
    loginLink.textContent = "로그아웃";
    loginLink.removeAttribute("href");
    loginLink.addEventListener("click", async (e) => {
      e.preventDefault();
      await window.LabBotAuth.signOut();
      if (window.LabBotNav) {
        window.LabBotNav.goTo("index.html");
      } else {
        window.location.href = "index.html";
      }
    });
  }

});
