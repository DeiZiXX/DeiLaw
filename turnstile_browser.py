"""One-time browser CAPTCHA for Windows clients of Supabase Auth.

No CAPTCHA secret belongs in a desktop application; only a public Turnstile
sitekey is configured. All token validation is performed by Supabase Auth.
The browser POSTs the response to a loopback-only HTTP server, never to URLs
with query strings or application logs. This is an aid for a staged rollout,
NOT a replacement for the Supabase CAPTCHA enforcement setting.
"""
from __future__ import annotations

import html
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_TOKEN_LENGTH = 2048

class CaptchaChallengeError(RuntimeError):
    pass


def get_turnstile_token(sitekey: str, *, browser_open=None,
                        cancel_event=None, timeout: int = 180) -> str:
    if not isinstance(sitekey, str) or not 6 <= len(sitekey.strip()) <= 256:
        raise CaptchaChallengeError("CAPTCHA sitekey не настроен.")
    sitekey = sitekey.strip()
    cancel = cancel_event or threading.Event()
    opener = browser_open or webbrowser.open_new_tab
    nonce = secrets.token_urlsafe(25)
    script_nonce = secrets.token_urlsafe(18)
    result = {}
    listener = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = listener.server_port
    origin = f"http://127.0.0.1:{port}"
    action_path = f"/{nonce}/finish"
    view_path = f"/{nonce}"
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
    <meta name="referrer" content="no-referrer"><title>DeiLaw CAPTCHA</title></head>
    <body style="font:17px Segoe UI,Arial,sans-serif;background:#141824;color:#fff;padding:35px">
    <h2>Подтверждение входа в DeiLaw</h2>
    <p>Подтвердите, что вы человек. После проверки вернитесь в программу.</p>
    <form id="challenge" method="post" action="{action_path}">
    <div class="cf-turnstile" data-sitekey="{html.escape(sitekey, quote=True)}"
      data-callback="completeChallenge"></div></form>
    <script nonce="{script_nonce}">
    function completeChallenge(token) {{
      if (typeof token !== 'string' || !token) return;
      document.getElementById('challenge').submit();
    }}
    </script>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
    </body></html>""".encode("utf-8")
    csp = ("default-src 'none'; base-uri 'none'; form-action 'self'; "
           "frame-src https://challenges.cloudflare.com; "
           "script-src https://challenges.cloudflare.com 'nonce-" + script_nonce + "'; "
           "style-src 'unsafe-inline'; connect-src 'self' https://challenges.cloudflare.com")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # Never log tokens or one-time paths.
            pass

        def respond(self, status: int, body: bytes, *, html_type=False):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html_type
                             else "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", csp)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def safe_host(self):
            return self.headers.get("Host", "") == f"127.0.0.1:{port}"

        def do_GET(self):
            if not self.safe_host() or urlsplit(self.path).path != view_path:
                return self.respond(404, b"Not found")
            self.respond(200, page, html_type=True)

        def do_POST(self):
            if not self.safe_host() or urlsplit(self.path).path != action_path:
                return self.respond(404, b"Not found")
            if self.headers.get("Origin") not in (None, origin):
                return self.respond(403, b"Invalid origin")
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
                return self.respond(415, b"Unsupported form encoding")
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.respond(400, b"Invalid request")
            if not 0 < size <= 4096:
                return self.respond(413, b"Invalid request size")
            form = parse_qs(self.rfile.read(size).decode("ascii", errors="replace"))
            token = str((form.get("cf-turnstile-response") or [""])[0])
            if not 1 <= len(token) <= MAX_TOKEN_LENGTH or any(ord(c)<33 or ord(c)>126 for c in token):
                return self.respond(400, b"Invalid token")
            if "token" in result:
                return self.respond(409, b"Already submitted")
            result["token"] = token
            self.respond(200, "CAPTCHA получена. Вернитесь в DeiLaw.".encode(), html_type=False)

    listener.RequestHandlerClass = Handler
    listener.timeout = 0.35
    try:
        if cancel.is_set() or not opener(origin + view_path):
            raise CaptchaChallengeError("Не удалось открыть браузер для CAPTCHA.")
        stop = time.monotonic() + max(10, min(int(timeout), 600))
        while time.monotonic() < stop and not cancel.is_set() and "token" not in result:
            listener.handle_request()
        if cancel.is_set():
            raise CaptchaChallengeError("CAPTCHA отменена.")
        if "token" not in result:
            raise CaptchaChallengeError("Время проверки CAPTCHA истекло.")
        return result["token"]
    finally:
        listener.server_close()
