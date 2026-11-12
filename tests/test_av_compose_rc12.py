"""Offline validation of the provider-neutral VPS antivirus deployment design."""
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
DIRECTORY=BASE/'security'/'av_gateway'

class TestAntivirusPackaging(unittest.TestCase):
    def test_no_public_scan_port(self):
        cfg=(DIRECTORY/'compose.yaml').read_text('utf-8')
        scanner=cfg.split('  scanner:',1)[1].split('\n  https:',1)[0]
        self.assertNotIn('\n    ports:',scanner)
        self.assertIn('no-new-privileges:true',scanner)
        self.assertIn('cap_drop:',scanner)
        self.assertIn('pids_limit:',scanner)
        self.assertIn('DEILAW_AV_SERVER_TOKEN:',scanner)

    def test_caddy_tls_and_request_limit(self):
        source=(DIRECTORY/'Caddyfile').read_text('utf-8')
        self.assertIn('{$DEILAW_AV_DOMAIN}',source)
        self.assertIn('max_size 11MB',source)
        self.assertIn('reverse_proxy scanner:10000',source)
        self.assertIn('respond "Not found" 404',source)

    def test_docker_env_not_packaged(self):
        self.assertFalse((DIRECTORY/'.env').exists())
        self.assertTrue((DIRECTORY/'.env.example').exists())
        self.assertIn('.env', (DIRECTORY/'.dockerignore').read_text('utf-8'))

    def test_missing_clamscan_binary_is_unhealthy(self):
        from security.av_gateway import clamav_gateway
        with patch.object(clamav_gateway.shutil,'which',return_value=None):
            self.assertFalse(clamav_gateway.signatures_fresh())

    def test_old_or_missing_signature_files_fail_closed(self):
        from security.av_gateway import clamav_gateway
        with tempfile.TemporaryDirectory() as folder, patch.object(clamav_gateway.shutil,'which',return_value='/usr/bin/clamscan'):
            with patch.dict(os.environ, {'DEILAW_AV_DB_DIR':folder, 'DEILAW_AV_MAX_SIGNATURE_HOURS':'48'}):
                self.assertFalse(clamav_gateway.signatures_fresh())
                path=Path(folder)/'daily.cld'
                path.write_bytes(b'dummy testing fixture')
                (Path(folder)/'main.cvd').write_bytes(b'dummy testing fixture')
                self.assertTrue(clamav_gateway.signatures_fresh())  # Presence/time only; ClamAV validates signatures while scanning.
                old=time.time()-72*3600
                os.utime(path,(old,old))
                self.assertFalse(clamav_gateway.signatures_fresh())

if __name__=='__main__':unittest.main()
