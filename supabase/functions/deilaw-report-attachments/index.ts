import { createClient } from "npm:@supabase/supabase-js@2.119.0";

const BUCKET = "bug-report-attachments";
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_FILES_PER_REPORT = 5;
const ALLOWED_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".txt", ".log"]);

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": [
    "apikey",
    "authorization",
    "content-type",
    "x-file-name-b64",
  ].join(", "),
  "Access-Control-Expose-Headers": "content-disposition, content-type, x-file-name-b64",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json; charset=utf-8" },
  });
}

function secretKey(): string {
  const modern = Deno.env.get("SUPABASE_SECRET_KEYS") ?? "";
  if (modern) {
    try {
      const parsed = JSON.parse(modern);
      if (parsed && typeof parsed === "object") {
        const preferred = parsed.default;
        if (typeof preferred === "string" && preferred.trim()) return preferred.trim();
        for (const value of Object.values(parsed)) {
          if (typeof value === "string" && value.trim()) return value.trim();
        }
      }
    } catch (_) {}
  }
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  if (legacy.trim()) return legacy.trim();
  throw new Error("Supabase secret key is unavailable");
}

function allowedPublishableKeys(): Set<string> {
  const result = new Set<string>();
  const modern = Deno.env.get("SUPABASE_PUBLISHABLE_KEYS") ?? "";
  if (modern) {
    try {
      const parsed = JSON.parse(modern);
      if (parsed && typeof parsed === "object") {
        for (const value of Object.values(parsed)) {
          if (typeof value === "string" && value.trim()) result.add(value.trim());
        }
      }
    } catch (_) {}
  }
  const legacy = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
  if (legacy.trim()) result.add(legacy.trim());
  return result;
}

function decodeFilename(value: string | null): string {
  if (!value) return "";
  try {
    let normalized = value.replace(/-/g, "+").replace(/_/g, "/");
    while (normalized.length % 4) normalized += "=";
    const binary = atob(normalized);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes).trim();
  } catch (_) {
    return "";
  }
}

function safeAttachmentName(filename: string): boolean {
  return Boolean(filename && filename.length <= 255 && filename !== "." && filename !== ".." &&
    !/[\\/\u0000-\u001f\u007f]/.test(filename));
}

function validAttachmentSignature(ext: string, body: Uint8Array): boolean {
  if (ext === ".png") return body.length >= 8 &&
    [137,80,78,71,13,10,26,10].every((c,i) => body[i] === c);
  if (ext === ".jpg" || ext === ".jpeg") return body.length >= 3 &&
    body[0] === 255 && body[1] === 216 && body[2] === 255;
  if (ext === ".webp") return body.length >= 12 &&
    String.fromCharCode(...body.slice(0,4)) === "RIFF" &&
    String.fromCharCode(...body.slice(8,12)) === "WEBP";
  if (ext === ".txt" || ext === ".log") return !body.includes(0);
  // No archive upload until ZIP decompression/malware scanning exists.
  return false;
}

function extensionOf(filename: string): string {
  const lower = filename.toLowerCase();
  const dot = lower.lastIndexOf(".");
  return dot >= 0 ? lower.slice(dot) : "";
}

function normalizedContentType(filename: string, requested: string | null): string {
  const ext = extensionOf(filename);
  const known: Record<string, string> = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".log": "text/plain",
  };
  return known[ext] ?? requested?.split(";")[0]?.trim() ?? "application/octet-stream";
}

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const admin = createClient(supabaseUrl, secretKey(), {
  auth: { persistSession: false, autoRefreshToken: false },
});

async function antivirusApproved(bytes: Uint8Array): Promise<boolean> {
  const endpointRaw = (Deno.env.get("DEILAW_AV_SCAN_URL") ?? "").trim();
  const token = (Deno.env.get("DEILAW_AV_TOKEN") ?? "").trim();
  if (!endpointRaw || token.length < 32) return false;
  let endpoint: URL;
  try {
    endpoint = new URL(endpointRaw);
    if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.hash) return false;
  } catch (_) { return false; }
  const buffer = await crypto.subtle.digest("SHA-256", bytes);
  const digest = Array.from(new Uint8Array(buffer))
    .map(x => x.toString(16).padStart(2, "0")).join("");
  try {
    const res = await fetch(endpoint.toString(), {
      method: "POST", redirect: "error",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/octet-stream" },
      body: bytes, signal: AbortSignal.timeout(20000),
    });
    if (!res.ok) return false;
    const verdict = await res.json();
    return verdict?.verdict === "clean" && verdict?.sha256 === digest;
  } catch (_) { return false; }
}

async function authenticatedUserId(req: Request): Promise<string | null> {
  const auth = req.headers.get("authorization") ?? "";
  if (!auth.toLowerCase().startsWith("bearer ")) return null;
  const token = auth.slice(7).trim();
  if (!token) return null;

  const { data, error } = await admin.auth.getUser(token);
  if (error || !data.user?.id) return null;
  return data.user.id;
}

async function isAdmin(userId: string): Promise<boolean> {
  const { data: rows, error: adminError } = await admin
    .from("deilaw_admins")
    .select("user_id")
    .eq("user_id", userId)
    .limit(1);
  return !adminError && Array.isArray(rows) && rows.length > 0;
}

async function authorizeReport(userId: string, reportId: string): Promise<boolean> {
  const { data: report, error } = await admin
    .from("bug_reports")
    .select("owner_uid")
    .eq("id", reportId)
    .maybeSingle();

  if (error || !report) return false;
  if (report.owner_uid === userId) return true;
  return await isAdmin(userId);
}

async function readBoundedBody(req: Request): Promise<Uint8Array | null> {
  const reader = req.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_FILE_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const output = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return output;
}

async function attachmentWithReport(attachmentId: string) {
  const { data, error } = await admin
    .from("bug_report_attachments")
    .select("id,report_id,object_path,original_name,content_type,size_bytes,created_at")
    .eq("id", attachmentId)
    .maybeSingle();
  if (error || !data) return null;
  return data;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const apiKey = (req.headers.get("apikey") ?? "").trim();
  if (!apiKey || !allowedPublishableKeys().has(apiKey)) {
    return json({ error: "Invalid publishable key" }, 401);
  }

  const userId = await authenticatedUserId(req);
  if (!userId) return json({ error: "Valid user JWT required" }, 401);

  const url = new URL(req.url);
  const action = (url.searchParams.get("action") ?? "").trim().toLowerCase();

  try {
    if (req.method === "GET" && action === "list") {
      const reportId = (url.searchParams.get("report_id") ?? "").trim();
      if (!reportId) return json({ error: "report_id is required" }, 400);
      if (!(await authorizeReport(userId, reportId))) return json({ error: "Forbidden" }, 403);

      const { data, error } = await admin
        .from("bug_report_attachments")
        .select("id,report_id,original_name,content_type,size_bytes,created_at")
        .eq("report_id", reportId)
        .order("created_at", { ascending: true });
      if (error) return json({ error: "Attachment service unavailable" }, 500);
      return json({ attachments: data ?? [] });
    }

    if (req.method === "GET" && action === "download") {
      const attachmentId = (url.searchParams.get("attachment_id") ?? "").trim();
      if (!attachmentId) return json({ error: "attachment_id is required" }, 400);

      const attachment = await attachmentWithReport(attachmentId);
      if (!attachment) return json({ error: "Attachment not found" }, 404);
      if (!(await authorizeReport(userId, String(attachment.report_id)))) {
        return json({ error: "Forbidden" }, 403);
      }

      const { data: blob, error } = await admin.storage
        .from(BUCKET)
        .download(String(attachment.object_path));
      if (error || !blob) return json({ error: "Download failed" }, 500);

      const filename = String(attachment.original_name ?? "attachment");
      const encodedName = btoa(
        String.fromCharCode(...new TextEncoder().encode(filename))
      ).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");

      return new Response(await blob.arrayBuffer(), {
        status: 200,
        headers: {
          ...corsHeaders,
          "Content-Type": String(attachment.content_type ?? "application/octet-stream"),
          "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`,
          "X-Content-Type-Options": "nosniff",
          "Cache-Control": "private, no-store",
          "X-File-Name-B64": encodedName,
        },
      });
    }

    if (req.method === "POST" && action === "upload") {
      const reportId = (url.searchParams.get("report_id") ?? "").trim();
      if (!reportId) return json({ error: "report_id is required" }, 400);
      if (!(await authorizeReport(userId, reportId))) return json({ error: "Forbidden" }, 403);

      const filename = decodeFilename(req.headers.get("x-file-name-b64"));
      if (!safeAttachmentName(filename)) return json({ error: "Invalid filename" }, 400);

      const ext = extensionOf(filename);
      if (!ALLOWED_EXTENSIONS.has(ext)) {
        return json({ error: "Unsupported file type" }, 400);
      }

      const body = await readBoundedBody(req);
      if (body === null) return json({ error: "File is larger than 10 MB" }, 413);
      if (body.byteLength <= 0) return json({ error: "Empty file" }, 400);
      if (!validAttachmentSignature(ext, body)) {
        return json({ error: "File contents do not match the allowed format" }, 400);
      }
      if (!await antivirusApproved(body)) {
        return json({ error: "Antivirus scanning unavailable or the file was rejected" }, 503);
      }

      const { count, error: countError } = await admin
        .from("bug_report_attachments")
        .select("id", { count: "exact", head: true })
        .eq("report_id", reportId);
      if (countError) return json({ error: "Unable to count attachments" }, 500);
      if ((count ?? 0) >= MAX_FILES_PER_REPORT) {
        return json({ error: "Maximum 5 attachments per report" }, 409);
      }

      const objectPath = `${reportId}/${crypto.randomUUID()}${ext}`;
      const contentType = normalizedContentType(filename, req.headers.get("content-type"));

      const { error: uploadError } = await admin.storage
        .from(BUCKET)
        .upload(objectPath, body, { contentType, upsert: false });
      if (uploadError) return json({ error: "Upload failed" }, 500);

      const { data: inserted, error: metaError } = await admin
        .from("bug_report_attachments")
        .insert({
          report_id: reportId,
          object_path: objectPath,
          original_name: filename,
          content_type: contentType,
          size_bytes: body.byteLength,
        })
        .select("id,report_id,original_name,content_type,size_bytes,created_at")
        .single();

      if (metaError) {
        await admin.storage.from(BUCKET).remove([objectPath]);
        return json({ error: "Attachment metadata failed" }, 500);
      }

      await admin
        .from("bug_reports")
        .update({ updated_at: new Date().toISOString() })
        .eq("id", reportId);

      return json({ attachment: inserted }, 201);
    }

    return json({ error: "Unsupported action" }, 404);
  } catch (_) {
    return json({ error: "Attachment request failed" }, 500);
  }
});
