// LabBot - 회원가입 페이지 스크립트 (Supabase Auth 이메일/비밀번호 회원가입)
// profiles 행 생성과 role='user' 기본값은 DB 트리거가 처리하므로 여기서는 auth 가입만 요청한다.

document.addEventListener("DOMContentLoaded", () => {
  const signupForm = document.getElementById("signupForm");
  const errorEl = document.getElementById("signupError");
  const infoEl = document.getElementById("signupInfo");
  const loginLink = document.getElementById("loginLink");

  const params = new URLSearchParams(window.location.search);
  // redirect 파라미터를 그대로 믿지 않는다 — 허용된 내부 페이지 목록에 없으면 index.html로.
  const redirectTo = window.LabBotAuth.sanitizeRedirect(params.get("redirect"));

  if (loginLink) {
    loginLink.href = `login.html?redirect=${encodeURIComponent(redirectTo)}`;
  }

  signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.style.display = "none";
    if (infoEl) infoEl.style.display = "none";

    const name = document.getElementById("name").value.trim();
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;
    const passwordConfirm = document.getElementById("passwordConfirm").value;

    if (password !== passwordConfirm) {
      errorEl.textContent = "비밀번호가 서로 일치하지 않습니다.";
      errorEl.style.display = "block";
      return;
    }

    let result;
    try {
      result = await window.LabBotAuth.signUp({ name, email, password });
    } catch (err) {
      errorEl.textContent =
        err.message === "User already registered" ? "이미 가입된 이메일입니다." : "회원가입에 실패했습니다. 다시 시도해주세요.";
      errorEl.style.display = "block";
      return;
    }

    // 이메일 인증이 켜져 있으면 가입 직후에는 세션이 없다 — 로그인 페이지로 안내
    if (!result.session) {
      if (infoEl) {
        infoEl.textContent = "가입 확인 이메일을 보냈습니다. 메일함을 확인한 뒤 로그인해주세요.";
        infoEl.style.display = "block";
      }
      signupForm.reset();
      return;
    }

    if (window.LabBotNav) {
      window.LabBotNav.goTo(redirectTo);
    } else {
      window.location.href = redirectTo;
    }
  });
});
