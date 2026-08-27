// LabBot - 로그인 페이지 스크립트 (Supabase Auth 이메일/비밀번호 로그인)

document.addEventListener("DOMContentLoaded", () => {
  const loginForm = document.getElementById("loginForm");
  const errorEl = document.getElementById("loginError");
  const signupLink = document.getElementById("signupLink");

  const params = new URLSearchParams(window.location.search);
  // redirect 파라미터를 그대로 믿지 않는다 — 허용된 내부 페이지 목록에 없으면 index.html로.
  const redirectTo = window.LabBotAuth.sanitizeRedirect(params.get("redirect"));

  if (signupLink) {
    signupLink.href = `signup.html?redirect=${encodeURIComponent(redirectTo)}`;
  }

  // Supabase가 돌려준 실패 원인을 사용자가 취할 수 있는 행동으로 번역한다.
  // 예전에는 무엇이 틀렸든 "비밀번호가 올바르지 않습니다"로 뭉뚱그려서,
  // 메일 인증을 안 끝낸 사람이 비밀번호만 계속 다시 치는 상황이 생겼다.
  function loginErrorMessage(err) {
    const raw = (err && (err.message || String(err))) || "";
    if (/email not confirmed|not confirmed/i.test(raw)) {
      return "메일 인증이 아직 안 끝났습니다. 가입할 때 받은 인증 메일을 확인해주세요.";
    }
    if (/rate limit|too many/i.test(raw)) {
      return "시도가 너무 잦습니다. 잠시 후 다시 시도해주세요.";
    }
    if (/failed to fetch|network/i.test(raw)) {
      return "서버에 연결하지 못했습니다. 인터넷 연결을 확인해주세요.";
    }
    return "이메일 또는 비밀번호가 올바르지 않습니다.";
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.style.display = "none";

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    // 제출 중 버튼을 잠근다 — 안 그러면 Enter를 연타할 때 로그인 요청이 동시에 여러 개 나간다.
    const submitBtn = loginForm.querySelector('button[type="submit"]');
    const originalLabel = submitBtn ? submitBtn.textContent : null;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "로그인 중…";
    }

    try {
      await window.LabBotAuth.signIn({ email, password });
    } catch (err) {
      errorEl.textContent = loginErrorMessage(err);
      errorEl.style.display = "block";
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalLabel;
      }
      return;
    }

    if (window.LabBotNav) {
      window.LabBotNav.goTo(redirectTo);
    } else {
      window.location.href = redirectTo;
    }
  });
});
