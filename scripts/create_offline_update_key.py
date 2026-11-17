"""Generate a passphrase-protected Ed25519 update key ON THE OWNER'S OFFLINE PC.

Never run this in CI or in a chat environment. This script never uploads the
private key; it prints only the public half to be pinned in update_trust.py.
"""
from __future__ import annotations

import base64
import getpass
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_key(destination: Path, passphrase: str, project_root: Path = PROJECT_ROOT) -> str:
    destination = destination.expanduser().resolve()
    if destination.is_relative_to(project_root.resolve()):
        raise ValueError("Private key must be stored OUTSIDE the repository.")
    if len(passphrase) < 16:
        raise ValueError("Use a passphrase of at least 16 characters.")
    if destination.exists():
        raise FileExistsError("Existing key will never be overwritten.")
    private = Ed25519PrivateKey.generate()
    encrypted_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement of existing secrets.
    with destination.open("xb") as stream:
        stream.write(encrypted_pem)
    if os.name == "posix":
        destination.chmod(0o600)
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public_raw).decode("ascii")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage (OFFLINE Windows PC): python scripts/create_offline_update_key.py D:\\SAFE\\DeiLaw_Ed25519.pem")
        return 2
    if not sys.stdin.isatty():
        print("Interactive offline terminal required. Never run in GitHub Actions.", file=sys.stderr)
        return 1
    first = getpass.getpass("Offline Ed25519 key passphrase (minimum 16 characters): ")
    second = getpass.getpass("Confirm passphrase: ")
    if first != second:
        print("Passphrases do not match.", file=sys.stderr)
        return 1
    try:
        public = generate_key(Path(sys.argv[1]), first)
    except (ValueError, FileExistsError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Public key (safe to commit to update_trust.py):", public)
    print("PRIVATE KEY CREATED ONLY AT REQUESTED LOCAL PATH. Keep offline backups; never commit, attach, or upload it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
