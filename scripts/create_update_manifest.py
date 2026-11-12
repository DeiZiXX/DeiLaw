"""Generate an unsigned manifest to sign with sign_update_manifest.py offline."""
import hashlib
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        raise SystemExit("Usage: create_update_manifest.py VERSION INSTALLER.exe OUTPUT.json")
    version, installer_arg, output_arg = sys.argv[1:]
    installer = Path(installer_arg).resolve()
    output = Path(output_arg).resolve()
    if not installer.is_file() or installer.suffix.lower() != ".exe":
        raise SystemExit("Installer .exe does not exist.")
    digest = hashlib.sha256()
    with installer.open("rb") as handle:
        while data := handle.read(1024 * 1024):
            digest.update(data)
    payload = {
        "version": version,
        "installer_asset": installer.name,
        "sha256": digest.hexdigest(),
        "size": installer.stat().st_size,
        "mandatory": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Unsigned manifest created: {output}")


if __name__ == "__main__":
    main()
