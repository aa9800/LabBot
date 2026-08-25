// LabBot - 인증 공통 스크립트 (Supabase Auth 기반)
// 비밀번호는 Supabase Auth가 처리 — 이 코드는 비밀번호를 저장하거나 직접 비교하지 않는다.
// 가입 시 profiles 행은 DB 트리거(handle_new_user, docs/labbot_schema.sql)가 자동 생성하며 role은 'user'로 시작한다.
// 관리자 권한은 이 파일이 아니라 DB의 RLS 정책(is_admin())으로 강제된다 — 여기서의 role 값은 화면 표시용일 뿐이다.
// 모든 페이지에서 supabase-client.js, nav.js보다 먼저 로드되어야 함 (window.LabBotAuth 제공)

async function fetchProfile(userId) {
  const { data, error } = await supabaseClient
    .from("profiles")
    .select("name, role")
    .eq("id", userId)
    .single();

  if (error) {
    console.error("LabBot: 프로필 조회 실패", error);
    return null;
  }
  return data;
}

async function signUp({ name, email, password }) {
  const { data, error } = await supabaseClient.auth.signUp({
    email,
    password,
    options: { data: { name } },
  });
  if (error) throw error;
  return data;
}

async function signIn({ email, password }) {
  const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
  if (error) throw error;
  return data;
}

async function signOut() {
  await supabaseClient.auth.signOut();
}

async function getSession() {
  const {
    data: { session },
  } = await supabaseClient.auth.getSession();

  if (!session) return null;

  const profile = await fetchProfile(session.user.id);
  return {
    id: session.user.id,
    email: session.user.email,
    name: (profile && profile.name) || session.user.email,
    role: (profile && profile.role) || "user",
  };
}

// login.html?redirect=... 값을 그대로 믿고 이동시키면, 로그인 성공 후
// login.html?redirect=https://evil.com 같은 링크로 외부 사이트로 보내는 오픈 리다이렉트가
// 된다. 내부 페이지 허용목록에 있는 값만 통과시키고, 아니면 무조건 index.html로 보낸다.
const REDIRECT_ALLOWLIST = ["index.html", "items.html", "mypage.html", "chatbot.html", "admin.html"];

function sanitizeRedirect(value) {
  return REDIRECT_ALLOWLIST.includes(value) ? value : "index.html";
}

// 로그인이 안 되어 있으면 로그인 페이지로 보내고 null을 반환, 되어 있으면 세션을 반환
async function requireLogin(redirectPage) {
  const session = await getSession();
  if (!session) {
    const target = `login.html?redirect=${encodeURIComponent(redirectPage || "index.html")}`;
    if (window.LabBotNav) {
      window.LabBotNav.goTo(target);
    } else {
      window.location.href = target;
    }
    return null;
  }
  return session;
}

window.LabBotAuth = {
  signUp,
  signIn,
  signOut,
  getSession,
  requireLogin,
  sanitizeRedirect,
};
