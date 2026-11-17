"""Validate confidential offline key generation and tamper-proof update flags."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization

import update_trust
from scripts.create_offline_update_key import generate_key, PROJECT_ROOT


class OfflineSigningKeyTests(unittest.TestCase):
    def test_key_is_encrypted_and_only_public_half_is_printable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "offline" / "release_ed25519.pem"
            public = generate_key(path, "never-share-this-passphrase")
            self.assertEqual(len(base64.b64decode(public)), 32)
            self.assertIn(b"ENCRYPTED PRIVATE KEY", path.read_bytes())
            private = serialization.load_pem_private_key(
                path.read_bytes(), password=b"never-share-this-passphrase"
            )
            manifest = {
                "version": "0.3.1",
                "installer_asset": "DeiLaw_Setup_v0.3.1.exe",
                "sha256": "a" * 64,
                "size": 10000,
                "mandatory": False,
            }
            manifest["signature_ed25519"] = base64.b64encode(
                private.sign(update_trust.signed_manifest_bytes(manifest))
            ).decode("ascii")
            with patch.object(update_trust, "UPDATE_ED25519_PUBLIC_KEY_B64", public):
                self.assertTrue(update_trust.verify_manifest(manifest))
                altered = dict(manifest)
                altered["mandatory"] = True
                with self.assertRaises(update_trust.UntrustedUpdateError):
                    update_trust.verify_manifest(altered)

    def test_private_key_cannot_be_overwritten_or_stored_under_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "key.pem"
            generate_key(path, "long-secret-for-testing")
            with self.assertRaises(FileExistsError):
                generate_key(path, "long-secret-for-testing")
        with self.assertRaises(ValueError):
            generate_key(PROJECT_ROOT / "THIS_FILE_MUST_NOT_EXIST.pem", "long-secret-for-testing")
        with self.assertRaises(ValueError):
            generate_key(Path(temp) / "not-created.pem", "short")

if __name__ == "__main__":
    unittest.main()
