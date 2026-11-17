"""Offline Ed25519 manifest signer. Never copy private keys into the repo.

Usage:
  python scripts/sign_update_manifest.py /secure/key.pem update_manifest.json
"""
import base64
import getpass
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from update_trust import signed_manifest_bytes


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: sign_update_manifest.py PRIVATE_KEY.pem update_manifest.json")
    private_key_path = Path(sys.argv[1]).resolve()
    manifest_path = Path(sys.argv[2]).resolve()
    if private_key_path.is_relative_to(Path(__file__).resolve().parent.parent):
        raise SystemExit("Signing key must be stored OUTSIDE the source repository.")
    pem = private_key_path.read_bytes()
    password = None
    if b"ENCRYPTED PRIVATE KEY" in pem:
        if not sys.stdin.isatty():
            raise SystemExit("Offline interactive terminal is required for an encrypted signing key.")
        password = getpass.getpass("Offline signing key passphrase: ").encode("utf-8")
    try:
        key = serialization.load_pem_private_key(pem, password=password)
    except (ValueError, TypeError) as exc:
        raise SystemExit("Unable to load offline signing key (wrong passphrase or key format).") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("Expected an Ed25519 signing key, not another private key algorithm.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["signature_ed25519"] = base64.b64encode(
        key.sign(signed_manifest_bytes(manifest))
    ).decode("ascii")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("Manifest signed. Keep PRIVATE_KEY.pem offline and never upload it.")


if __name__ == "__main__":
    main()
