// LabBot - Supabase 연결 설정 템플릿
// 이 프로젝트는 번들러 없는 정적 사이트라서, web/.env 대신 이 파일로 접속 정보를 관리합니다.
//
// 사용법:
//   1) 이 파일을 복사해서 같은 폴더에 "config.js"로 저장
//   2) Supabase 대시보드 > Project Settings > API 에서 아래 두 값을 확인해서 채우기
//      (Supabase 프로젝트에 팀원으로 초대되어 있어야 이 화면을 볼 수 있음 — CONTRIBUTING.md 참고)
//   3) config.js는 git에 올라가지 않습니다 (.gitignore에 이미 등록되어 있음)
//
// anon key는 RLS(Row Level Security)로 보호되는 것을 전제로 브라우저에 노출되어도 되는 키입니다.
// service_role 키는 절대 이 파일에도, 어떤 프론트엔드 코드에도 넣지 않습니다.

window.LABBOT_SUPABASE_CONFIG = {
  url: "https://여기에-프로젝트고유주소.supabase.co",
  anonKey: "여기에-anon-public-key",
};
