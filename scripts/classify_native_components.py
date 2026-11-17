"""Review matrix for actual native Windows files. NOT a license determination."""
import json
import sys
from pathlib import Path

NATIVE_SUFFIXES = {".dll", ".exe", ".pyd"}
GROUP_INFO = {
    "qt": "Check Qt version, plugin licenses, LGPL replacement and Qt third-party SBOM",
    "microsoft_runtime": "MSVC/UCRT redistribution terms; SignPath OSI policy needs explicit resolution",
    "openssl": "Confirm OpenSSL 3 license and included notices",
    "cpython": "Confirm Python PSF license stack and native runtime provenance",
    "other_native": "Resolve origin and actual license of each extension, DLL and bootloader",
    "deilaw": "Confirm code/media rights, release sources and PyInstaller bootloader exception",
}

def classify(path):
    name = path.lower().rsplit("/", 1)[-1]
    low = path.lower()
    if path == "DeiLaw.exe":
        return "deilaw"
    if name.startswith(("msvcp", "vcruntime", "ucrt", "api-ms-win")):
        return "microsoft_runtime"
    if low.startswith("_internal/pyqt6/qt6/") or low.startswith("_internal/pyqt6/") and name in ("qtcore.pyd", "qtgui.pyd", "qtwidgets.pyd"):
        return "qt"
    if name in ("libssl-3.dll", "libcrypto-3.dll"):
        return "openssl"
    if name.startswith("python3") or low.startswith("_internal/") and name in {
        "_asyncio.pyd", "_bz2.pyd", "_ctypes.pyd", "_decimal.pyd",
        "_elementtree.pyd", "_hashlib.pyd", "_lzma.pyd",
        "_multiprocessing.pyd", "_overlapped.pyd", "_queue.pyd",
        "_socket.pyd", "_sqlite3.pyd", "_ssl.pyd", "_uuid.pyd",
        "_wmi.pyd", "pyexpat.pyd", "select.pyd", "unicodedata.pyd",
        "winsound.pyd",
    }:
        return "cpython"
    return "other_native"

def classify_inventory(inventory):
    rows = inventory.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Invalid build inventory")
    groups = {group: {"review": reason, "files": []} for group, reason in GROUP_INFO.items()}
    seen = set()
    for entry in rows:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or path in seen:
            raise ValueError("Missing or duplicate inventory filename")
        seen.add(path)
        if Path(path).suffix.lower() in NATIVE_SUFFIXES:
            groups[classify(path)]["files"].append({
                "path": path, "sha256": entry.get("sha256"),
            })
    if len(groups["deilaw"]["files"]) != 1:
        raise ValueError("DeiLaw.exe not present")
    for group in groups.values():
        group["files"].sort(key=lambda f: f["path"])
    return {
        "schema": "deilaw-native-review-v1",
        "classification_only_not_legal_clearance": True,
        "release_clearance_status": "BLOCKED_MANUAL_REVIEW",
        "counts": {key: len(group["files"]) for key, group in groups.items()},
        "groups": groups,
    }

def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: classify_native_components.py build_inventory.json output.json")
    report = classify_inventory(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Native Windows components for manual review:", report["counts"])
    print("NOT A LICENSE CLEARANCE. Do not merge/publish/sign without human review.")

if __name__ == "__main__":
    main()
