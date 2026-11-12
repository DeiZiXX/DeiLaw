"""Public Turnstile Sitekey. NEVER put the Cloudflare secret key here.

After creating a production Turnstile widget whose allowed hostname includes
127.0.0.1, set this public sitekey and rebuild. The Supabase CAPTCHA secret
must be configured separately in Auth > Bot and Abuse Protection.
"""
import os
TURNSTILE_PUBLIC_SITEKEY_FOR_RELEASE = ""  # Public only; set before building official EXE.
TURNSTILE_SITE_KEY = os.environ.get("DEILAW_TURNSTILE_SITE_KEY", "").strip() or TURNSTILE_PUBLIC_SITEKEY_FOR_RELEASE
