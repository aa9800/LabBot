// LabBot - 파손 신고 사진을 제미나이 비전으로 분석해서 파손 정도를 자동 판정하는 Edge Function.
// 흐름: 사용자가 mypage에서 파손 신고(사진 업로드 + damage_reports 행 insert, status='pending')
//       -> 클라이언트가 이 함수를 report_id로 호출
//       -> 이 함수가 photo_url의 사진을 읽어 제미나이 비전에 보내고
//       -> 결과를 damage_reports.severity/ai_result/status에 service role로 기록
// 제미나이 API 키/서비스롤 키는 이 함수의 secret에만 있고 브라우저 코드에는 절대 노출 안 됨.

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const GEMINI_MODEL = "gemini-3.6-flash"; // gemini-2.5-flash는 신규 사용자에게 더 이상 제공 안 됨(404)

const SEVERITY_LEVELS = ["경미", "보통", "심각", "즉시교체"];

// 파손 판정 결과를 최대한 정형화된 JSON으로 강제 — 파싱 실패를 줄이려고 responseSchema를 같이 보낸다.
const RESULT_SCHEMA = {
  type: "object",
  properties: {
    severity: { type: "string", enum: SEVERITY_LEVELS },
    summary: { type: "string" },
    recommended_action: { type: "string" },
  },
  required: ["severity", "summary", "recommended_action"],
};

// 사진 바이너리를 base64로 변환 — 큰 이미지는 한 번에 String.fromCharCode(...bytes)하면
// 콜스택이 터질 수 있어서 청크 단위로 나눠 처리한다.
function bytesToBase64(bytes: Uint8Array): string {
  const CHUNK = 8192;
  let binary = "";
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

async function fetchImageAsBase64(url: string): Promise<{ base64: string; mimeType: string }> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`사진을 불러오지 못했습니다 (${res.status})`);
  const mimeType = res.headers.get("content-type") || "image/jpeg";
  const bytes = new Uint8Array(await res.arrayBuffer());
  return { base64: bytesToBase64(bytes), mimeType };
}

async function assessWithGemini(imageBase64: string, mimeType: string, itemName: string, itemCategory: string, note: string) {
  const apiKey = Deno.env.get("GEMINI_API_KEY");
  if (!apiKey) throw new Error("GEMINI_API_KEY secret이 설정되어 있지 않습니다.");

  const prompt = `당신은 실험실 물품 파손 정도를 판정하는 어시스턴트입니다.
아래 물품의 파손 신고 사진을 보고 파손 정도를 평가하세요.

물품명: ${itemName}
분류: ${itemCategory}
신고자 메모: ${note || "(없음)"}

파손 정도는 반드시 다음 4단계 중 하나로만 답하세요: 경미 / 보통 / 심각 / 즉시교체
- 경미: 외관상 흠집 등 기능에 영향 없음
- 보통: 사용은 가능하나 주의가 필요한 손상
- 심각: 정상 사용이 어려운 손상, 수리 필요
- 즉시교체: 안전사고 위험이 있거나 수리 불가능한 손상

summary는 사진에서 확인되는 손상 내용을 한 문장으로,
recommended_action은 관리자가 취해야 할 다음 조치를 한두 문장으로 답하세요.`;

  const body = {
    contents: [
      {
        role: "user",
        parts: [
          { text: prompt },
          { inlineData: { mimeType, data: imageBase64 } },
        ],
      },
    ],
    generationConfig: {
      responseMimeType: "application/json",
      responseSchema: RESULT_SCHEMA,
    },
  };

  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }
  );

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`제미나이 API 오류(${res.status}): ${errText}`);
  }

  const data = await res.json();
  const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!text) throw new Error("제미나이 응답에서 결과 텍스트를 찾지 못했습니다.");

  const parsed = JSON.parse(text);
  if (!SEVERITY_LEVELS.includes(parsed.severity)) {
    throw new Error(`알 수 없는 severity 값: ${parsed.severity}`);
  }
  return parsed;
}

// service role(LABBOT_SERVICE_KEY)로 damage_reports 행을 직접 갱신 — RLS를 우회해야
// (일반 사용자는 ai_result/status/severity를 직접 못 고치게 막아뒀으므로) 이 함수만 쓸 수 있다.
async function patchDamageReport(reportId: number, patch: Record<string, unknown>) {
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("LABBOT_SERVICE_KEY");
  const res = await fetch(`${supabaseUrl}/rest/v1/damage_reports?id=eq.${reportId}`, {
    method: "PATCH",
    headers: {
      apikey: serviceKey!,
      Authorization: `Bearer ${serviceKey}`,
      "content-type": "application/json",
      prefer: "return=representation",
    },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    throw new Error(`damage_reports 갱신 실패(${res.status}): ${await res.text()}`);
  }
  return res.json();
}

async function fetchDamageReport(reportId: number) {
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("LABBOT_SERVICE_KEY");
  const res = await fetch(
    `${supabaseUrl}/rest/v1/damage_reports?id=eq.${reportId}&select=id,photo_url,note,items(name,category)`,
    {
      headers: { apikey: serviceKey!, Authorization: `Bearer ${serviceKey}` },
    }
  );
  if (!res.ok) throw new Error(`damage_reports 조회 실패(${res.status}): ${await res.text()}`);
  const rows = await res.json();
  return rows[0] ?? null;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }

  // 이 함수는 로그인한 사용자만 호출할 수 있게 supabaseClient.functions.invoke()가
  // 자동으로 실어 보내는 Authorization(사용자 JWT)이 있는지만 확인한다 — 실제 DB 접근은
  // service role로 하되, 신고 자체는 본인이 이미 RLS(damage_insert_own)를 통과해 만든
  // 행이라 report_id를 안다는 것 자체가 신고 당사자이거나 URL을 공유받은 경우뿐이다.
  const authHeader = req.headers.get("authorization");
  if (!authHeader) {
    return new Response(JSON.stringify({ error: "로그인이 필요합니다." }), {
      status: 401,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  }

  let reportId: number;
  try {
    const payload = await req.json();
    reportId = Number(payload.report_id);
    if (!reportId) throw new Error("report_id가 필요합니다.");
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message || "잘못된 요청입니다." }), {
      status: 400,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  }

  try {
    const report = await fetchDamageReport(reportId);
    if (!report) {
      return new Response(JSON.stringify({ error: "해당 파손 신고를 찾을 수 없습니다." }), {
        status: 404,
        headers: { ...CORS_HEADERS, "content-type": "application/json" },
      });
    }

    const { base64, mimeType } = await fetchImageAsBase64(report.photo_url);
    const result = await assessWithGemini(
      base64,
      mimeType,
      report.items?.name ?? "알 수 없음",
      report.items?.category ?? "-",
      report.note ?? ""
    );

    await patchDamageReport(reportId, {
      status: "analyzed",
      severity: result.severity,
      ai_result: JSON.stringify(result),
    });

    return new Response(JSON.stringify({ ok: true, result }), {
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  } catch (err) {
    console.error("[gemini-damage-assess]", err);
    await patchDamageReport(reportId, {
      status: "failed",
      ai_result: JSON.stringify({ error: String(err.message || err) }),
    }).catch(() => {}); // 갱신마저 실패해도 아래 에러 응답은 그대로 내려준다

    return new Response(JSON.stringify({ error: err.message || "분석 중 오류가 발생했습니다." }), {
      status: 500,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  }
});
