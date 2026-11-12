"""Strict trust boundary for DeiLaw GitHub Releases.

A checksum in the same release is not an authenticity proof. Release metadata
must be signed offline using an Ed25519 key whose PUBLIC half is pinned into
the desktop binary. Keep the private key completely out of the repository.
"""
import base64
import json
import re


# Release engineer: generate an offline signing key, place ONLY the public key
# here, rebuild the app, then publish signed manifests. Empty means fail closed.
UPDATE_ED25519_PUBLIC_KEY_B64 = ""


class UntrustedUpdateError(RuntimeError):
    pass


def signed_manifest_bytes(manifest):
    fields = ("version", "installer_asset", "sha256", "size")
    if not isinstance(manifest, dict) or any(name not in manifest for name in fields):
        raise UntrustedUpdateError("Не хватает подписываемых полей обновления.")
    if not re.fullmatch(r"[a-f0-9]{64}", str(manifest["sha256"]).lower()):
        raise UntrustedUpdateError("Некорректный SHA-256 обновления.")
    if not isinstance(manifest["size"], int) or manifest["size"] <= 0:
        raise UntrustedUpdateError("Некорректный размер обновления.")
    name = str(manifest["installer_asset"])
    if not name.lower().endswith(".exe") or "/" in name or "\\" in name or name.startswith("."):
        raise UntrustedUpdateError("Недопустимое имя установщика.")
    payload = {name: manifest[name] for name in fields}
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def verify_manifest(manifest):
    data = signed_manifest_bytes(manifest)
    if not UPDATE_ED25519_PUBLIC_KEY_B64:
        raise UntrustedUpdateError(
            "Автоматические обновления приостановлены: "
            "не настроен ключ проверки подписи релиза."
        )
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public_key = base64.b64decode(UPDATE_ED25519_PUBLIC_KEY_B64, validate=True)
        signature = base64.b64decode(str(manifest["signature_ed25519"]), validate=True)
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except Exception as exc:
        raise UntrustedUpdateError(
            "Подпись обновления недействительна. Установка отменена."
        ) from exc
    return True
