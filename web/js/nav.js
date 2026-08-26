// LabBot - 공통 네비게이션 스크립트

// 로그인한 사용자의 문의 중 "답변완료"인데 아직 안 알려준 게 있으면 토스트로 알려준다.
// 페이지를 옮길 때마다(로그인 상태로 있는 한 매 페이지에서) 확인하지만, 한 번 알려준
// 문의 id는 localStorage에 남겨둬서 같은 답변을 또 알려주지 않는다.
async function notifyAnsweredInquiries(session) {
  if (!window.LabBotInquiry || !window.LabBotToast) return;

  try {
    const inquiries = await window.LabBotInquiry.fetchMyInquiries(session.id);
    const answered = inquiries.filter((q) => q.status === "answered");
    if (answered.length === 0) return;

    const key = `labbot_notified_inquiry_ids_${session.id}`;
    const notifiedIds = new Set(JSON.parse(localStorage.getItem(key) || "[]"));
    const newlyAnswered = answered.filter((q) => !notifiedIds.has(q.id));
    if (newlyAnswered.length === 0) return;

    window.LabBotToast.success(
      newlyAnswered.length === 1
        ? `"${newlyAnswered[0].subject}" 문의에 답변이 도착했습니다.`
        : `문의 ${newlyAnswered.length}건에 답변이 도착했습니다.`
    );
    newlyAnswered.forEach((q) => notifiedIds.add(q.id));
    localStorage.setItem(key, JSON.stringify([...notifiedIds]));
  } catch (err) {
    console.warn("LabBot: 문의 답변 알림 확인 실패", err);
  }
}

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

  if (session) {
    notifyAnsweredInquiries(session);
  }
});
