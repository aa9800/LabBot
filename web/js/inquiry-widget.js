// LabBot - 문의하기 플로팅 버튼 공용 스크립트
// 모든 페이지에서 같은 버튼(#inquiryFabBtn)을 쓰므로, 이 파일 하나로 전부 처리한다.
// 로그인한 사용자만 문의를 남길 수 있다 — 비로그인 상태면 안내만 하고 모달을 열지 않는다.

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("inquiryFabBtn");
  if (!btn || !window.LabBotAuth) return;

  btn.addEventListener("click", async () => {
    const session = await window.LabBotAuth.getSession();
    if (!session) {
      window.LabBotToast.info("로그인 후 문의를 남길 수 있습니다.");
      return;
    }
    openInquiryModal(session);
  });
});

function openInquiryModal(session) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
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

  const close = () => {
    document.removeEventListener("keydown", onKeydown);
    overlay.remove();
  };
  const onKeydown = (e) => {
    if (e.key === "Escape") close();
  };
  document.addEventListener("keydown", onKeydown);

  overlay.querySelector('[data-action="close"]').addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close(); // 배경 클릭으로도 닫히게
  });

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
