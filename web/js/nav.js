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

// 재입고 알림을 신청해둔 물품 중 재고가 다시 생긴 게 있으면 토스트로 알려주고,
// 알려준 신청 건은 서버에서 바로 지운다(consumeRestockNotification) — 그래서
// 위 답변 알림과 달리 localStorage로 "이미 봤는지"를 따로 추적할 필요가 없다.
async function notifyRestockedItems(session) {
  if (!window.LabBotRestock || !window.LabBotToast) return;

  try {
    const ready = await window.LabBotRestock.fetchReadyRestockNotifications(session.id);
    if (ready.length === 0) return;

    window.LabBotToast.success(
      ready.length === 1
        ? `"${ready[0].items.name}" 물품이 재입고되었습니다.`
        : `재입고 알림 ${ready.length}건 — 신청하신 물품이 다시 들어왔습니다.`
    );

    await Promise.all(ready.map((row) => window.LabBotRestock.consumeRestockNotification(row.id)));
  } catch (err) {
    console.warn("LabBot: 재입고 알림 확인 실패", err);
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

  // 관리자로 로그인했을 때만 관리자 링크를 보여준다(사용자 요청). admin.html이
  // requireLogin()으로 바뀐 뒤로는 비로그인 상태에서 이 링크가 없어도 주소를 직접
  // 입력하면 로그인 페이지로 안내되고, 로그인하면 자동으로 admin.html로 돌아오므로
  // 여기서 미리 노출해 둘 필요가 없다. UI 노출용 편의 기능일 뿐, 실제 접근 차단은
  // DB의 is_admin() RLS가 담당한다.
  if (adminLink) {
    adminLink.style.display = session && session.role === "admin" ? "inline" : "none";
  }

  if (loginLink && session) {
    loginLink.textContent = "로그아웃";
    loginLink.removeAttribute("href");
    loginLink.addEventListener("click", async (e) => {
      e.preventDefault();
      // 대화기록 초기화(사용자 요청)는 signOut()보다 먼저 해야 한다 — 로그아웃한
      // 뒤에는 auth.uid()가 없어져서 RLS가 삭제 자체를 막는다. 이 페이지에
      // chat-data.js가 없을 수도 있어서(관리자 화면 등) 있을 때만 호출한다.
      if (window.LabBotChat) {
        await window.LabBotChat.clearChatHistory(session);
      }
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
    notifyRestockedItems(session);
  }
});
