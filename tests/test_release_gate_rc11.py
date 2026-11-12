"""Regression tests for fail-closed release, backup and antivirus integration."""
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from security.backup_encrypted import prerequisites

ROOT=pathlib.Path(__file__).resolve().parents[1]

class TestReleaseGate(unittest.TestCase):
 def test_powershell_signs_inner_exe_and_installer(self):
  code=(ROOT/'build_release.ps1').read_text('utf-8')
  self.assertIn("dist\\DeiLaw\\DeiLaw.exe",code)
  self.assertIn("& $SignTool sign /sha1 $CertificateThumbprint",code)
  self.assertEqual(code.count('SignTool sign /sha1'),2)
  self.assertEqual(code.count('SignTool verify /pa /v'),2)
  self.assertNotIn('http://timestamp.digicert.com',code)
 def test_release_without_key_fails_closed(self):
  from update_trust import verify_manifest,UntrustedUpdateError
  import update_trust
  original=update_trust.UPDATE_ED25519_PUBLIC_KEY_B64
  try:
   update_trust.UPDATE_ED25519_PUBLIC_KEY_B64=''
   with self.assertRaises(UntrustedUpdateError):
    verify_manifest({'version':'0.3.5rc11','installer_asset':'DeiLaw_Setup_v0.3.5rc11.exe','sha256':'0'*64,'size':1000,'signature_ed25519':'AAAA'})
  finally:update_trust.UPDATE_ED25519_PUBLIC_KEY_B64=original
 def test_attachment_gateway_fail_closed(self):
  s=(ROOT/'supabase/functions/deilaw-report-attachments/index.ts').read_text('utf-8')
  self.assertIn('if (!await antivirusApproved(body))',s)
  self.assertIn('if (!endpointRaw || token.length < 32) return false',s)
  self.assertIn('verdict?.verdict === "clean" && verdict?.sha256 === digest',s)
  self.assertIn('redirect: "error"',s)
  self.assertIn('AbortSignal.timeout(20000)',s)
  self.assertIn('"X-Content-Type-Options": "nosniff"',s)
 def test_backup_requires_offsite_and_tls(self):
  with tempfile.TemporaryDirectory() as d:
   env={'PGHOST':'db.example.com','PGDATABASE':'postgres','PGUSER':'postgres','PGPASSWORD':'not-real','PGSSLMODE':'disable'}
   with mock.patch('security.backup_encrypted.shutil.which',return_value='/usr/bin/tool'):
    with self.assertRaisesRegex(ValueError,'PGSSLMODE'):
     prerequisites(env,'a'*40,pathlib.Path(d))
    env['PGSSLMODE']='require'
    prerequisites(env,'a'*40,pathlib.Path(d))
    with self.assertRaisesRegex(ValueError,'exact 40- or 64'):
     prerequisites(env,'not-a-key',pathlib.Path(d))
 def test_private_keys_not_bundled(self):
  bad=[x for x in ROOT.rglob('*') if x.is_file() and x.suffix.lower() in ('.pfx','.p12','.pem','.key')]
  self.assertFalse(bad,'Signing keys or certificates must never be included: '+str(bad))

if __name__=='__main__': unittest.main()
