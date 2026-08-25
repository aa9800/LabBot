// LabBot - 챗봇 Edge Function. 제미나이 API 키는 이 함수의 secret에만 있고 브라우저에는 노출 안 됨.
// 입력: { message: string, items: [{id, name, location, available_qty, total_qty}] }
// 출력: { reply: string, recommended_item_ids: number[] }
// recommended_item_ids는 챗봇 화면에서 "사용하기"/"대여하기" 버튼이 달린 카드로 바로 보여주는 데 쓴다 —
// 그래서 서버가 실제로 지금 목록에 있는 item id만 골라 정수 배열로 돌려주도록 강제한다(문자열 파싱 금지).

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const GEMINI_MODEL = "gemini-3.6-flash"; // gemini-2.5-flash는 신규 사용자에게 더 이상 제공 안 됨(404)

const RESULT_SCHEMA = {
  type: "object",
  properties: {
    reply: { type: "string" },
    recommended_item_ids: { type: "array", items: { type: "integer" } },
  },
  required: ["reply", "recommended_item_ids"],
};

function buildItemContext(items) {
  if (!Array.isArray(items) || items.length === 0) return "(등록된 물품 없음)";
  return items
    .map((it) => `id=${it.id} ${it.name}(${it.location}, 대여가능 ${it.available_qty}/${it.total_qty})`)
    .join("\n");
}

async function askGemini(message, items) {
  const apiKey = Deno.env.get("GEMINI_API_KEY");
  if (!apiKey) throw new Error("GEMINI_API_KEY secret이 설정되어 있지 않습니다.");

  const prompt = `당신은 LabBot이라는 실험실 물품 대여관리 시스템의 챗봇입니다.
아래는 지금 실제로 등록된 물품 목록입니다 (id, 이름, 위치, 대여가능수량/총수량):

${buildItemContext(items)}

사용자 질문: "${message}"

규칙:
- 위 목록에 실제로 있는 물품만 추천하세요. 목록에 없는 물품을 지어내지 마세요.
- 사용자에게 필요한 물품이 있으면 recommended_item_ids에 해당 물품들의 id를 담으세요 (최대 3개).
- 추천할 물품이 없으면 recommended_item_ids는 빈 배열로 두세요.
- reply는 친절하고 간결한 한국어 답변 한두 문단으로 작성하세요. id 숫자를 답변 문장에 직접 언급하지 마세요
  (id는 카드 UI로 별도 표시되니 자연스러운 물품 이름으로만 언급하세요).`;

  const body = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
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

  // 서버가 존재하지 않는 id를 잘못 돌려줘도 클라이언트가 안전하게 무시할 수 있게,
  // 여기서 한 번 더 실제 목록에 있는 id로만 걸러준다.
  const validIds = new Set((items || []).map((it) => it.id));
  const recommended_item_ids = (parsed.recommended_item_ids || []).filter((id) => validIds.has(id));

  return { reply: parsed.reply, recommended_item_ids };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }

  try {
    const { message, items } = await req.json();
    if (!message || typeof message !== "string") {
      throw new Error("message가 필요합니다.");
    }

    const result = await askGemini(message, items);

    return new Response(JSON.stringify(result), {
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  } catch (err) {
    console.error("[gemini-chat]", err);
    return new Response(
      JSON.stringify({ reply: "챗봇 응답을 가져오지 못했어요. 잠시 후 다시 시도해주세요.", recommended_item_ids: [], error: err.message || String(err) }),
      { status: 500, headers: { ...CORS_HEADERS, "content-type": "application/json" } }
    );
  }
});
