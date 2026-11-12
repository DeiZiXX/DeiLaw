"""Small HTTPS-reverse-proxy-backed ClamAV gateway for Supabase Edge Functions.

Linux VM/container only; listen on 127.0.0.1:8787 and terminate TLS at a
separately configured reverse proxy. ClamAV signature updates are required.
Do NOT expose raw HTTP to the internet.
Environment: DEILAW_AV_SERVER_TOKEN (strong random secret), DEILAW_AV_HOST,
DEILAW_AV_PORT; clamscan CLI installed (clamav + clamav-freshclam).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BYTES=10*1024*1024
SCAN_SLOTS=threading.BoundedSemaphore(2)

def signatures_fresh() -> bool:
    """Scanner must have recent daily and main signatures; fail closed otherwise."""
    if shutil.which('clamscan') is None:
        return False
    directory=Path(os.getenv('DEILAW_AV_DB_DIR','/var/lib/clamav'))
    try:
        age=int(os.getenv('DEILAW_AV_MAX_SIGNATURE_HOURS','48'))
    except ValueError:
        return False
    if not 6<=age<=168:return False
    now=time.time()
    for base in ('daily','main'):
        files=[directory/(base+ext) for ext in ('.cld','.cvd')]
        existing=[f for f in files if f.is_file()]
        if not existing:return False
        if base=='daily' and not any(0 <= now-f.stat().st_mtime <= age*3600 for f in existing):
            return False
    return True

class Handler(BaseHTTPRequestHandler):
    server_version='DeiLaw-AV/1'
    sys_version=''
    def log_message(self, fmt, *args):
        # Never log filenames, tokens, file bytes or request content.
        return
    def answer(self, code:int, data:dict) -> None:
        b=json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(b)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(b)
    def do_POST(self):
        if self.path!='/scan':
            self.answer(404,{'error':'not_found'});return
        secret=os.environ.get('DEILAW_AV_SERVER_TOKEN','')
        provided=self.headers.get('Authorization','')
        if len(secret)<32 or not hmac.compare_digest(provided,'Bearer '+secret):
            self.answer(401,{'error':'unauthorized'});return
        if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/octet-stream':
            self.answer(415,{'error':'invalid_content_type'});return
        if not signatures_fresh():
            self.answer(503,{'error':'scanner_signatures_unavailable'});return
        if not SCAN_SLOTS.acquire(blocking=False):
            self.answer(503,{'error':'scanner_busy'});return
        try:
            self.connection.settimeout(25)
            return self._scan_authenticated()
        finally:
            SCAN_SLOTS.release()

    def _scan_authenticated(self):
        try:
            size=int(self.headers.get('Content-Length',''))
        except ValueError:
            self.answer(411,{'error':'content_length_required'});return
        if not 0<size<=MAX_BYTES:
            self.answer(413,{'error':'size_limit'});return
        payload=self.rfile.read(size)
        if len(payload)!=size:
            self.answer(400,{'error':'incomplete_file'});return
        digest=hashlib.sha256(payload).hexdigest()
        try:
            with tempfile.TemporaryDirectory(prefix='deilaw-av-') as temp:
                location=os.path.join(temp,'upload.bin')
                with open(location,'xb') as out:
                    out.write(payload)
                result=subprocess.run(['clamscan','--no-summary','--stdout',location],
                    capture_output=True, timeout=25, check=False)
                if result.returncode==0:
                    self.answer(200,{'verdict':'clean','sha256':digest})
                elif result.returncode==1:
                    self.answer(200,{'verdict':'infected','sha256':digest})
                else:
                    self.answer(503,{'error':'scanner_failed'})
        except (OSError,subprocess.TimeoutExpired):
            self.answer(503,{'error':'scanner_unavailable'})
    def do_GET(self):
        if self.path=='/health':
            self.answer(200 if signatures_fresh() else 503,
                        {'ready':signatures_fresh()})
            return
        self.answer(404,{'error':'not_found'})


def main():
    if hasattr(os,'geteuid') and os.geteuid()==0 and os.getenv('DEILAW_AV_ALLOW_ROOT')!='1':
        raise SystemExit('Run the scanner gateway as an unprivileged OS user')
    if len(os.getenv('DEILAW_AV_SERVER_TOKEN',''))<32:
        raise SystemExit('Set a long random DEILAW_AV_SERVER_TOKEN')
    host=os.getenv('DEILAW_AV_HOST','127.0.0.1')
    if host not in ('127.0.0.1','::1') and not (
        host=='0.0.0.0' and os.getenv('DEILAW_AV_TRUSTED_INGRESS')=='1'):
        raise SystemExit('Bind localhost, or use 0.0.0.0 ONLY behind trusted HTTPS ingress')
    port=int(os.getenv('DEILAW_AV_PORT',os.getenv('PORT','8787')))
    http=ThreadingHTTPServer((host,port),Handler)
    http.daemon_threads=True
    http.serve_forever()

if __name__=='__main__':
    main()
