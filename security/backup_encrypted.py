"""Encrypt an offsite PostgreSQL logical backup *without* plaintext staging.

Needs pg_dump and GnuPG installed on the backup machine, a separately stored
GPG recipient public key, and PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD.

Example (PowerShell):
  $env:PGHOST='db.<project>.supabase.co'; $env:PGSSLMODE='require'
  $env:PGUSER='postgres'; $env:PGDATABASE='postgres'
  $env:PGPASSWORD=Read-Host 'Database password' -AsSecureString  # see guide
  python security/backup_encrypted.py --recipient FINGERPRINT --destination X:\\Backup

The backup destination MUST be independent of the Supabase project.
A logical database dump does NOT include Storage object bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_PG = ('PGHOST', 'PGDATABASE', 'PGUSER', 'PGPASSWORD')


def prerequisites(env: dict[str, str], recipient: str, destination: Path) -> None:
    missing = [k for k in REQUIRED_PG if not env.get(k)]
    if missing:
        raise ValueError('Missing PostgreSQL environment variables: ' + ', '.join(missing))
    if not re.fullmatch(r'[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?', recipient):
        raise ValueError('Use an exact 40- or 64-digit OpenPGP recipient fingerprint')
    if not shutil.which('pg_dump') or not shutil.which('gpg'):
        raise RuntimeError('pg_dump and gpg must be installed and available in PATH')
    if not destination.is_dir():
        raise ValueError('Offsite destination folder does not exist')
    if destination.resolve() == Path.cwd().resolve():
        raise ValueError('Offsite backup cannot be stored in the source directory')
    if env.get('PGSSLMODE', '').lower() not in ('verify-ca', 'verify-full', 'require'):
        raise ValueError('Set PGSSLMODE=require (or verify-full with PGSSLROOTCERT)')


def encrypted_backup(recipient: str, destination: Path, env: dict[str, str] | None = None) -> Path:
    cfg = dict(os.environ if env is None else env)
    prerequisites(cfg, recipient, destination)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = destination / f'DeiLaw-postgres-{timestamp}.dump.gpg'
    temp_output = destination / f'.{output.name}.incomplete'
    if output.exists() or temp_output.exists():
        raise FileExistsError('Backup path exists; refusing overwrite')
    cfg['PGCONNECT_TIMEOUT'] = cfg.get('PGCONNECT_TIMEOUT', '20')
    with tempfile.TemporaryFile() as pg_err, tempfile.TemporaryFile() as gpg_err:
        pg = subprocess.Popen(
            ['pg_dump', '--format=custom', '--no-owner', '--no-privileges', '--no-password'],
            stdout=subprocess.PIPE, stderr=pg_err, env=cfg,
        )
        try:
            gp = subprocess.Popen(
                ['gpg', '--batch', '--yes', '--encrypt', '--recipient', recipient,
                 '--output', str(temp_output)],
                stdin=pg.stdout, stdout=subprocess.DEVNULL, stderr=gpg_err,
            )
            assert pg.stdout is not None
            pg.stdout.close()
            gpg_rc = gp.wait()
            pg_rc = pg.wait()
            if pg_rc != 0 or gpg_rc != 0:
                raise RuntimeError(f'Backup/encryption failed (pg_dump={pg_rc}, gpg={gpg_rc}). Check credentials and recipient key. No partial file was kept.')
            if not temp_output.is_file() or temp_output.stat().st_size < 100:
                raise RuntimeError('Encrypted backup is missing or unexpectedly short')
            temp_output.replace(output)
        except BaseException:
            if pg.poll() is None:
                pg.kill()
            pg.wait()
            temp_output.unlink(missing_ok=True)
            raise
    with output.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    metadata = {'name': output.name, 'sha256': digest, 'size_bytes': output.stat().st_size,
                'created_at_utc': timestamp, 'format': 'pg_dump custom + OpenPGP',
                'note': 'Database logical backup only; Storage bucket file contents require separate export.'}
    (destination / f'{output.name}.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    print(f'Encrypted DB backup: {output}\nSHA256: {digest}')
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipient', required=True, help='GPG recipient public key fingerprint')
    parser.add_argument('--destination', required=True, type=Path, help='Independent offsite/mounted folder')
    args = parser.parse_args()
    encrypted_backup(args.recipient, args.destination)


if __name__ == '__main__':
    main()
