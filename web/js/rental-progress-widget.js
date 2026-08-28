// LabBot - 대여 진행률 바 (화면 하단 중앙, 챗봇 버튼과 같은 높이)
// 사용자 요청("대여 신청을 했을때 진행률에 따라 따로 표기") — 예약(loans.status='예약중')
// 이 있는 동안 화면 어디서나 "지금 몇 단계인지"를 보여준다. DB에는 예약중/대여중/반납완료
// 세 상태만 있고 "로봇 안내 받는 중"은 따로 저장하지 않으므로(모달을 열어둔 순간의 화면
// 상태일 뿐), 예약중인 동안은 계속 2단계(로봇 안내·QR 대기)로 표시하고 대여중으로 바뀌는
// 순간 3단계 완료로 보고 바를 숨긴다 — 실제 서버 데이터만으로 정직하게 표현한다.

document.addEventListener("DOMContentLoaded", async () => {
  if (!window.LabBotAuth || !window.LabBotRentals) return;

  const session = await window.LabBotAuth.getSession();
  if (!session) return; // 로그인 안 했으면 예약 자체가 없으니 조용히 종료

  let reserved;
  try {
    const loans = await window.LabBotRentals.fetchMyLoans(session.id);
    reserved = loans.filter((loan) => loan.status === "예약중");
  } catch (err) {
    console.warn("LabBot: 대여 진행률 바 데이터를 불러오지 못했습니다", err);
    return;
  }

  if (reserved.length === 0) return; // 수령 대기중인 예약이 없으면 바 자체를 안 띄운다

  const label =
    reserved.length === 1
      ? `"${reserved[0].items.name}" 수령 대기중`
      : `${reserved.length}건의 물품이 수령 대기중`;

  const bar = document.createElement("button");
  bar.type = "button";
  bar.className = "rental-progress-bar";
  bar.setAttribute("role", "status");
  bar.setAttribute("aria-label", `${label} — 눌러서 마이페이지로 이동`);
  bar.innerHTML = `
    <span class="rp-label">${window.LabBotItems ? window.LabBotItems.escapeHtml(label) : label}</span>
    <span class="rp-track">
      <span class="rp-dot rp-done"></span>
      <span class="rp-line rp-done"></span>
      <span class="rp-dot rp-current"></span>
      <span class="rp-line"></span>
      <span class="rp-dot"></span>
    </span>
    <span class="rp-hint">마이페이지에서 계속하기 →</span>
  `;
  bar.addEventListener("click", () => {
    if (window.LabBotNav) {
      window.LabBotNav.goTo("mypage.html");
    } else {
      window.location.href = "mypage.html";
    }
  });

  document.body.appendChild(bar);
});
