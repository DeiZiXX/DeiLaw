"""Desktop Discord OAuth through Supabase Auth, using a PKCE loopback callback.

Only the public Supabase key lives in DeiLaw. Discord's OAuth client secret
belongs exclusively in the Supabase provider configuration.
"""

import base64
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser


# Configure this exact URL under Authentication > URL Configuration in Supabase.
# Discord itself redirects to Supabase /auth/v1/callback, NOT this listener.
DISCORD_LOOPBACK_HOST = "127.0.0.1"
DISCORD_LOOPBACK_PORT = 45831
DISCORD_LOOPBACK_PATH = "/deilaw-auth"
DISCORD_REDIRECT_URL = (
    f"http://{DISCORD_LOOPBACK_HOST}:{DISCORD_LOOPBACK_PORT}{DISCORD_LOOPBACK_PATH}"
)


class DiscordOAuthError(RuntimeError):
    pass


def new_pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


def authorization_url(supabase_url, challenge):
    query = urlencode({
        "provider": "discord",
        "redirect_to": DISCORD_REDIRECT_URL,
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    })
    return f"{str(supabase_url).rstrip('/')}/auth/v1/authorize?{query}"


def complete_discord_pkce(supabase_url, *, cancel_event=None,
                          browser_open=None, timeout=180):
    """Wait for a one-time code and return it with its local PKCE verifier.

    Calls no Discord endpoint directly: Supabase owns the OAuth client secret,
    validates Discord's response, and exchanges this verifier for a JWT.
    """
    cancel = cancel_event or threading.Event()
    open_browser = browser_open or webbrowser.open_new_tab
    verifier, challenge = new_pkce_pair()
    result = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # Callback URLs contain one-time codes. Never put them in logs.
            return

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != DISCORD_LOOPBACK_PATH:
                self.send_error(404)
                return
            if len(self.path) > 2048:
                self.send_error(414)
                return
            query = parse_qs(parsed.query)
            code = str((query.get("code") or [""])[0])
            error = str((query.get("error_description") or
                         query.get("error") or [""])[0])
            if not code and not error:
                self.send_error(400)
                return
            result["code"] = code
            result["error"] = error
            message = (
                "Авторизация Discord завершена. Вернитесь в DeiLaw."
                if code else "Не удалось выполнить вход Discord. Вернитесь в DeiLaw."
            )
            page = (
                "<!doctype html><meta charset='utf-8'><title>DeiLaw</title>"
                "<body style='font:18px Segoe UI,Arial,sans-serif;"
                "background:#151820;color:white;padding:48px'>"
                f"<h2>{html.escape(message)}</h2></body>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    try:
        server = HTTPServer((DISCORD_LOOPBACK_HOST, DISCORD_LOOPBACK_PORT), CallbackHandler)
    except OSError as exc:
        raise DiscordOAuthError(
            "Порт входа Discord занят. Закройте другие копии DeiLaw и повторите попытку."
        ) from exc
    server.timeout = 0.5
    try:
        if cancel.is_set():
            raise DiscordOAuthError("Вход через Discord отменён.")
        if not open_browser(authorization_url(supabase_url, challenge)):
            raise DiscordOAuthError("Не удалось открыть браузер для входа Discord.")
        deadline = time.monotonic() + max(5, int(timeout))
        while time.monotonic() < deadline and not cancel.is_set() and not result:
            server.handle_request()
        if cancel.is_set():
            raise DiscordOAuthError("Вход через Discord отменён.")
        if result.get("error"):
            raise DiscordOAuthError("Discord отклонил авторизацию или вход отменён.")
        code = result.get("code")
        if not code:
            raise DiscordOAuthError("Время ожидания входа Discord истекло.")
        return code, verifier
    finally:
        server.server_close()
