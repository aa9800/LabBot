// LabBot - Supabase 클라이언트 초기화
// js/config.js(로컬 전용, git 미포함)의 값으로 전역 window.supabaseClient를 만든다.
// 로드 순서: (CDN) supabase-js -> config.js -> 이 파일 -> auth.js/nav.js 등 나머지 앱 스크립트

(function () {
  const config = window.LABBOT_SUPABASE_CONFIG;

  if (!config || !config.url || !config.anonKey) {
    console.error(
      "LabBot: js/config.js가 없거나 값이 비어 있습니다. js/config.example.js를 복사해서 config.js를 만들고 " +
        "Supabase 프로젝트의 URL/anon key를 채워주세요."
    );
    return;
  }

  window.supabaseClient = window.supabase.createClient(config.url, config.anonKey);
})();
