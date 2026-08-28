// LabBot - 문의하기 플로팅 버튼 공용 스크립트
// 모든 페이지에서 같은 버튼(#inquiryFabBtn)을 쓰므로, 이 파일 하나로 전부 처리한다.
// 로그인한 사용자만 문의를 남길 수 있다 — 비로그인 상태면 안내만 하고 모달을 열지 않는다.

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("inquiryFabBtn");
  if (!btn || !window.LabBotAuth) return;

  btn.addEventListener("click", async () => {
    // 이미 열려있으면 다시 눌렀을 때 닫히게(토글) — 취소 버튼을 굳이 안 눌러도 되도록.
    const existing = document.querySelector('.modal-overlay[data-modal="inquiry"]');
    if (existing) {
      existing.remove();
      btn.style.zIndex = ""; // 아래 openInquiryModal에서 올려둔 z-index 원복
      return;
    }

    const session = await window.LabBotAuth.getSession();
    if (!session) {
      window.LabBotToast.info("로그인 후 문의를 남길 수 있습니다.");
      return;
    }
    openInquiryModal(session, btn);
  });
});

function openInquiryModal(session, fabBtn) {
  // .modal-overlay는 z-index:300으로 전체 화면을 덮어서, 열려있는 동안 그 아래 깔린
  // FAB 버튼(z-index 없음)은 화면에 보여도 클릭이 오버레이한테 먹혀 버튼까지 안 닿는다.
  // 모달이 떠 있는 동안만 버튼을 오버레이보다 위로 올려서 "다시 누르면 닫힘"이 실제로
  // 동작하게 한다 — 닫히면(취소/제출성공/토글) 반드시 원복해야 한다.
  if (fabBtn) fabBtn.style.zIndex = "301";

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.dataset.modal = "inquiry"; // FAB 버튼 토글 클릭 시 이 모달만 식별해서 닫기 위함
  overlay.innerHTML = `
    <div class="modal-card">
      <h3 class="modal-title">관리자에게 문의하기</h3>
      <p class="modal-subtitle">보내신 문의와 답변은 마이페이지에서 확인할 수 있어요.</p>

      <div class="modal-field">
        <label for="inquirySubjectInput">제목</label>
        <input type="text" id="inquirySubjectInput" placeholder="예: 물품 반납 기한 문의" />
      </div>

      <div class="modal-field">
        <label for="inquiryMessageInput">내용</label>
        <textarea id="inquiryMessageInput" placeholder="문의하실 내용을 적어주세요" rows="4"></textarea>
      </div>

      <div class="modal-actions">
        <button type="button" class="btn btn-secondary btn-sm" data-action="close">취소</button>
        <button type="button" class="btn btn-primary btn-sm" data-action="submit">보내기</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector("#inquirySubjectInput").focus();

  // 취소/보내기 버튼으로만 닫힌다 — 사용자 요청으로 배경 클릭 닫기를 뺐다(입력 중 실수로
  // 바깥을 눌러 내용이 날아가는 걸 방지).
  const close = () => {
    overlay.remove();
    if (fabBtn) fabBtn.style.zIndex = "";
  };

  overlay.querySelector('[data-action="close"]').addEventListener("click", close);

  overlay.querySelector('[data-action="submit"]').addEventListener("click", async (e) => {
    const subject = overlay.querySelector("#inquirySubjectInput").value.trim();
    const message = overlay.querySelector("#inquiryMessageInput").value.trim();

    if (!subject || !message) {
      window.LabBotToast.error("제목과 내용을 모두 입력해주세요.");
      return;
    }

    const submitBtn = e.currentTarget;
    submitBtn.disabled = true;
    submitBtn.textContent = "전송 중...";
    try {
      await window.LabBotInquiry.submitInquiry(session, { subject, message });
      window.LabBotToast.success("문의가 접수되었습니다.");
      close();
    } catch (err) {
      window.LabBotToast.error(err.message || "문의 접수에 실패했습니다.");
      submitBtn.disabled = false;
      submitBtn.textContent = "보내기";
    }
  });
}
