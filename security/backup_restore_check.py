"""Offline integrity/readability check; NEVER restore into production.

Checks GPG decryption and pg_restore --list without writing decrypted dump to disk.
Requires GPG private key available on this machine and pg_restore binary.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def check(encrypted: Path) -> str:
    if not encrypted.is_file():
        raise FileNotFoundError(encrypted)
    if not shutil.which('gpg') or not shutil.which('pg_restore'):
        raise RuntimeError('gpg and pg_restore are required')
    metadata = encrypted.with_name(encrypted.name+'.json')
    if metadata.exists():
        expected = json.loads(metadata.read_text('utf-8')).get('sha256')
        with encrypted.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        if expected != digest:
            raise RuntimeError('Encrypted backup SHA256 mismatch')
    with tempfile.TemporaryFile() as gpg_err, tempfile.TemporaryFile() as restore_err:
        gpg = subprocess.Popen(['gpg','--batch','--decrypt',str(encrypted)], stdout=subprocess.PIPE, stderr=gpg_err)
        try:
            restore = subprocess.Popen(['pg_restore','--list'], stdin=gpg.stdout, stdout=subprocess.PIPE, stderr=restore_err)
            assert gpg.stdout is not None
            gpg.stdout.close()
            out = restore.communicate()[0]
            if restore.returncode or gpg.wait():
                raise RuntimeError('Unable to decrypt or read pg_dump archive')
            if b'; Archive created at' not in out[:2000]:
                raise RuntimeError('pg_restore did not recognize custom archive')
            return 'Backup decrypt/list verification PASSED (does not test restoration of live data)'
        finally:
            if gpg.poll() is None: gpg.kill()
            gpg.wait()

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('encrypted',type=Path)
    print(check(p.parse_args().encrypted))
