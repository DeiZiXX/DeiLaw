import { createClient } from "npm:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "apikey, content-type, x-deilaw-installation-id, x-deilaw-device-id, x-deilaw-app-version",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

const SYSTEM_PROMPT = `Ты — DeiLaw AI, RP-юридический помощник игрового сервера RMRP.

Твоя задача — анализировать RP-ситуации исключительно по нормам RMRP, которые переданы тебе приложением в текущем запросе.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Используй только переданные нормы RMRP. Не используй реальное законодательство РФ из памяти модели.
2. Не придумывай номера статей, названия документов, санкции, сроки, штрафы, полномочия, основания применения силы или оружия.
3. Если подходящей нормы среди переданных источников нет — так и укажи.
4. Если фактов недостаточно для точной квалификации — перечисли, что нужно уточнить.
5. Не считай совпадение отдельных слов достаточным основанием для квалификации.
6. Основная квалификация обычно должна опираться на КоАП/УК, а ПДД, ФЗ и процессуальные нормы могут быть дополнительными основаниями.
7. Санкцию указывай только если она прямо присутствует в тексте конкретной переданной нормы.
8. Действия сотрудника, применение силы, специальных средств или оружия указывай только при прямой опоре на переданную норму.
9. Учитывай предыдущие сообщения чата как контекст фактов, но не превращай прошлые предположения в доказанные обстоятельства.
10. Не делай категоричный вывод, если в источниках есть только косвенное совпадение.
11. Отвечай по-русски, кратко и структурированно.
12. Верни только JSON-объект, без Markdown и текста вне JSON.

СХЕМА JSON:
{
  "summary": "краткий вывод без выдуманных статей",
  "primary": [{"document":"документ","article":"номер","reason":"почему подходит"}],
  "additional": [{"document":"документ","article":"номер","reason":"почему связана"}],
  "responsibility": [{"document":"документ","article":"номер","text":"санкция только из текста нормы"}],
  "actions": [{"document":"документ","article":"номер","text":"действие сотрудника, подтвержденное нормой"}],
  "clarifications": ["что нужно уточнить"],
  "confidence": "high | medium | low"
}`;

type Source = {
  result_type?: string;
  law_title?: string;
  article_number?: string;
  article_title?: string;
  content?: string;
  score?: number;
};

type HistoryItem = { role?: string; content?: string };

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json; charset=utf-8" },
  });
}

function envFirstJsonValue(name: string): string | null {
  const raw = Deno.env.get(name) ?? "";
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw);
    if (obj && typeof obj === "object") {
      for (const value of Object.values(obj)) {
        if (typeof value === "string" && value.trim()) return value.trim();
      }
    }
  } catch (_) {
    // fall through
  }
  return null;
}

function allowedPublishableKeys(): Set<string> {
  const keys = new Set<string>();
  const raw = Deno.env.get("SUPABASE_PUBLISHABLE_KEYS") ?? "";
  if (raw) {
    try {
      const obj = JSON.parse(raw);
      if (obj && typeof obj === "object") {
        for (const value of Object.values(obj)) {
          if (typeof value === "string" && value.trim()) keys.add(value.trim());
        }
      }
    } catch (_) {
      // ignore malformed env and rely on legacy fallback
    }
  }
  const legacy = Deno.env.get("SUPABASE_ANON_KEY");
  if (legacy?.trim()) keys.add(legacy.trim());
  return keys;
}

function getSecretKey(): string | null {
  return (
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")?.trim() ||
    envFirstJsonValue("SUPABASE_SECRET_KEYS")
  );
}

function extractOutputText(payload: any): string {
  if (typeof payload?.output_text === "string" && payload.output_text.trim()) {
    return payload.output_text.trim();
  }
  for (const item of payload?.output ?? []) {
    for (const part of item?.content ?? []) {
      if (part?.type === "output_text" && typeof part?.text === "string" && part.text.trim()) {
        return part.text.trim();
      }
    }
  }
  return "";
}

function safeText(value: unknown, max: number): string {
  return String(value ?? "").trim().slice(0, max);
}

function renderSources(sources: Source[]): string {
  return sources
    .slice(0, 8)
    .map((s, index) => {
      return [
        `ИСТОЧНИК ${index + 1}`,
        `Тип: ${safeText(s.result_type, 50)}`,
        `Документ: ${safeText(s.law_title, 300)}`,
        `Статья: ${safeText(s.article_number, 80)}`,
        `Название: ${safeText(s.article_title, 500)}`,
        `Текст:\n${safeText(s.content, 6500)}`,
      ].join("\n");
    })
    .join("\n\n");
}

function renderHistory(history: HistoryItem[]): string {
  const rows: string[] = [];
  for (const item of history.slice(-6)) {
    const role = String(item?.role ?? "").toLowerCase();
    if (role !== "user" && role !== "assistant") continue;
    const content = safeText(item?.content, 3000);
    if (!content) continue;
    rows.push(`${role === "user" ? "Пользователь" : "DeiLaw AI"}: ${content}`);
  }
  return rows.join("\n\n");
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const clientKey = req.headers.get("apikey")?.trim() ?? "";
  const acceptedKeys = allowedPublishableKeys();
  if (!clientKey || !acceptedKeys.has(clientKey)) {
    return json({ error: "Доступ к DeiLaw Cloud AI запрещён." }, 401);
  }

  const model = Deno.env.get("OPENAI_MODEL")?.trim() || "gpt-6-luna";
  const openaiKey = Deno.env.get("OPENAI_API_KEY")?.trim() || "";

  if (req.method === "GET") {
    return json({
      ok: Boolean(openaiKey),
      service: "DeiLaw Cloud AI",
      model,
      configured: Boolean(openaiKey),
    }, openaiKey ? 200 : 503);
  }

  if (req.method !== "POST") {
    return json({ error: "Метод не поддерживается." }, 405);
  }

  if (!openaiKey) {
    return json({ error: "Cloud AI временно не настроен на сервере." }, 503);
  }

  const deviceId = req.headers.get("x-deilaw-device-id")?.trim().toLowerCase() ?? "";
  if (!/^[a-f0-9]{64}$/.test(deviceId)) {
    return json({ error: "Некорректный идентификатор устройства." }, 400);
  }

  let body: any;
  try {
    body = await req.json();
  } catch (_) {
    return json({ error: "Некорректный JSON запроса." }, 400);
  }

  const situation = safeText(body?.situation, 5000);
  const sources = Array.isArray(body?.sources) ? body.sources.slice(0, 8) : [];
  const history = Array.isArray(body?.history) ? body.history.slice(-6) : [];

  if (!situation) return json({ error: "RP-ситуация не заполнена." }, 400);
  if (!sources.length) return json({ error: "Нет источников для анализа." }, 400);

  const supabaseUrl = Deno.env.get("SUPABASE_URL")?.trim() || "";
  const secretKey = getSecretKey();
  if (!supabaseUrl || !secretKey) {
    return json({ error: "Сервер Cloud AI не может проверить лимит запросов." }, 503);
  }

  const dailyLimit = Math.max(1, Math.min(1000, Number(Deno.env.get("DEILAW_AI_DAILY_LIMIT") || "100") || 100));
  const admin = createClient(supabaseUrl, secretKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: quota, error: quotaError } = await admin.rpc("deilaw_claim_ai_request", {
    p_device_id: deviceId,
    p_daily_limit: dailyLimit,
  });

  if (quotaError) {
    console.error("quota error", quotaError);
    return json({ error: "Не удалось проверить лимит DeiLaw AI." }, 503);
  }

  const allowed = Boolean(quota?.allowed);
  const remaining = Number(quota?.remaining ?? 0);
  if (!allowed) {
    return json({
      error: `Дневной лимит DeiLaw AI исчерпан. Попробуйте снова завтра.`,
      remaining: 0,
    }, 429);
  }

  const historyText = renderHistory(history);
  const sourcesText = renderSources(sources);
  const input = [
    historyText ? `КОНТЕКСТ ДИАЛОГА:\n${historyText}` : "",
    `ТЕКУЩАЯ RP-СИТУАЦИЯ:\n${situation}`,
    `ЕДИНСТВЕННЫЕ РАЗРЕШЁННЫЕ ИСТОЧНИКИ RMRP:\n\n${sourcesText}`,
    "Проверь фактические признаки каждой нормы. Если данных недостаточно — не додумывай. Верни только JSON по заданной схеме.",
  ].filter(Boolean).join("\n\n");

  let openaiResponse: Response;
  try {
    openaiResponse = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${openaiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        instructions: SYSTEM_PROMPT,
        input,
        max_output_tokens: 1400,
        store: false,
      }),
    });
  } catch (error) {
    console.error("OpenAI fetch failed", error);
    return json({ error: "Не удалось связаться с AI-сервисом. Повторите запрос позже." }, 502);
  }

  let openaiPayload: any = null;
  try {
    openaiPayload = await openaiResponse.json();
  } catch (_) {
    // handled below
  }

  if (!openaiResponse.ok) {
    console.error("OpenAI error", openaiResponse.status, openaiPayload);
    return json({ error: "AI-сервис временно не смог обработать запрос." }, 502);
  }

  const answer = extractOutputText(openaiPayload);
  if (!answer) {
    return json({ error: "AI-сервис вернул пустой ответ." }, 502);
  }

  return json({
    answer,
    model: openaiPayload?.model || model,
    response_id: openaiPayload?.id || null,
    remaining,
    usage: openaiPayload?.usage || null,
  });
});
