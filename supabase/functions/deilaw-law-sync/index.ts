import { createClient } from "npm:@supabase/supabase-js@2.117.2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

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
  } catch (_) {}
  return null;
}

function publishableKey(): string | null {
  return Deno.env.get("SUPABASE_ANON_KEY")?.trim()
    || envFirstJsonValue("SUPABASE_PUBLISHABLE_KEYS");
}

function secretKey(): string | null {
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")?.trim()
    || envFirstJsonValue("SUPABASE_SECRET_KEYS");
}

function cleanText(value: unknown, max: number): string {
  return String(value ?? "").trim().slice(0, max);
}

function normalizeLawCode(title: string, supplied: unknown): string {
  const explicit = cleanText(supplied, 40).toLowerCase().replace(/ё/g, "е");
  if (explicit) return explicit;

  const t = title.toLowerCase().replace(/ё/g, "е");
  if (t.includes("кодекс об административных") || t.includes("коап")) return "коап";
  if (t.includes("уголовно-процесс") || t.includes("упк")) return "упк";
  if (t.includes("уголовн") || /(^|\s)ук(\s|$)/.test(t)) return "ук";
  if (t.includes("правила дорожного") || t.includes("пдд")) return "пдд";
  if (t.includes("процессуальн") || /(^|\s)пк(\s|$)/.test(t)) return "пк";
  if (t.includes("конституц")) return "конституция";
  if (t.includes("трудов")) return "тк";
  if (t.includes("бюджет")) return "бк";
  if (t.includes("избират")) return "избирательный";
  if (t.includes("федеральн") || t.includes("фз")) return "фз";
  return "другое";
}

async function requireAdmin(req: Request) {
  const url = Deno.env.get("SUPABASE_URL")?.trim() || "";
  const pub = publishableKey();
  const sec = secretKey();
  const auth = req.headers.get("Authorization")?.trim() || "";
  if (!url || !pub || !sec) throw new Error("server_not_configured");
  if (!auth.toLowerCase().startsWith("bearer ")) throw new Error("auth_required");

  const userClient = createClient(url, pub, {
    global: { headers: { Authorization: auth } },
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: userData, error: userError } = await userClient.auth.getUser();
  const user = userData?.user;
  if (userError || !user) throw new Error("auth_invalid");

  const { data: adminRow, error: adminError } = await userClient
    .from("deilaw_admins")
    .select("user_id")
    .eq("user_id", user.id)
    .maybeSingle();

  if (adminError || !adminRow) throw new Error("admin_required");

  const admin = createClient(url, sec, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return { admin, user };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Метод не поддерживается." }, 405);

  let ctx;
  try {
    ctx = await requireAdmin(req);
  } catch (error) {
    const code = String((error as Error)?.message || "");
    if (code === "admin_required") return json({ error: "Требуются права администратора DeiLaw." }, 403);
    if (code === "auth_required" || code === "auth_invalid") return json({ error: "Требуется вход администратора." }, 401);
    return json({ error: "Сервис синхронизации не настроен." }, 503);
  }

  let body: any;
  try { body = await req.json(); }
  catch (_) { return json({ error: "Некорректный JSON." }, 400); }

  const action = cleanText(body?.action, 40);
  const syncToken = cleanText(body?.sync_token, 80);
  if (!/^[0-9a-f-]{36}$/i.test(syncToken)) {
    return json({ error: "Некорректный sync_token." }, 400);
  }

  const { admin } = ctx;

  if (action === "upsert_law") {
    const law = body?.law ?? {};
    const title = cleanText(law?.title, 500);
    const url = cleanText(law?.url, 2000);
    const content = cleanText(law?.content, 500000);
    const code = normalizeLawCode(title, law?.law_code);
    const articles = Array.isArray(law?.articles) ? law.articles.slice(0, 1000) : [];

    if (!title || !url) return json({ error: "У закона нет title/url." }, 400);

    const { data: lawRow, error: lawError } = await admin
      .from("deilaw_laws")
      .upsert({
        title,
        law_code: code,
        url,
        content,
        source_updated_at: law?.updated_at || null,
        synced_at: new Date().toISOString(),
        sync_token: syncToken,
      }, { onConflict: "url" })
      .select("id")
      .single();

    if (lawError || !lawRow?.id) {
      console.error("law upsert", lawError);
      return json({ error: "Не удалось сохранить закон." }, 500);
    }

    const lawId = lawRow.id;
    const { error: deleteError } = await admin
      .from("deilaw_law_articles")
      .delete()
      .eq("law_id", lawId);
    if (deleteError) {
      console.error("article delete", deleteError);
      return json({ error: "Не удалось обновить статьи закона." }, 500);
    }

    const rows = articles
      .map((a: any) => ({
        law_id: lawId,
        law_title: title,
        law_code: code,
        law_url: url,
        article_number: cleanText(a?.article_number ?? a?.number, 100),
        article_title: cleanText(a?.article_title ?? a?.title, 1000) || null,
        content: cleanText(a?.content, 100000),
        synced_at: new Date().toISOString(),
      }))
      .filter((a: any) => a.article_number && a.content);

    for (let i = 0; i < rows.length; i += 200) {
      const { error } = await admin
        .from("deilaw_law_articles")
        .insert(rows.slice(i, i + 200));
      if (error) {
        console.error("article insert", error);
        return json({ error: "Не удалось загрузить статьи закона." }, 500);
      }
    }

    return json({ ok: true, law_id: lawId, law_code: code, articles: rows.length });
  }

  if (action === "finish") {
    const { data: deleted, error: finishError } = await admin
      .rpc("deilaw_finish_law_sync", { p_sync_token: syncToken });
    if (finishError) {
      console.error("finish sync", finishError);
      return json({ error: "Не удалось завершить синхронизацию." }, 500);
    }
    const { data: stats } = await admin.rpc("deilaw_law_corpus_stats");
    return json({ ok: true, deleted_old_laws: Number(deleted || 0), stats: stats || {} });
  }

  return json({ error: "Неизвестное действие." }, 400);
});
