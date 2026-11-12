"""Print the Ed25519 public key in the form used by update_trust.py.

The private key must remain outside this repository and should never be sent
over chat or uploaded to GitHub.
"""
import base64
import sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: show_update_public_key.py /secure/private.pem")
    private_key = serialization.load_pem_private_key(
        Path(sys.argv[1]).read_bytes(), password=None,
    )
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print(base64.b64encode(raw_public).decode("ascii"))


if __name__ == "__main__":
    main()
