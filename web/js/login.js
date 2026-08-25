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

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.style.display = "none";

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    try {
      await window.LabBotAuth.signIn({ email, password });
    } catch (err) {
      errorEl.textContent = "이메일 또는 비밀번호가 올바르지 않습니다.";
      errorEl.style.display = "block";
      return;
    }

    if (window.LabBotNav) {
      window.LabBotNav.goTo(redirectTo);
    } else {
      window.location.href = redirectTo;
    }
  });
});
