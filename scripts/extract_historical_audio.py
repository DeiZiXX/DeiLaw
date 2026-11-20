"""Read original PyInstaller CArchive audio without running the application."""
from __future__ import annotations
import json, sys, hashlib, zipfile
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader

def dump(archive, output, prefix="", max_depth=2):
    count = 0
    with_audio = []
    for name in archive.toc:
        if name.lower().endswith((".wav",".ogg",".flac",".mp3")):
            try:
                data = archive.extract(name)
                if isinstance(data, tuple):
                    data = data[1]
                if not isinstance(data, bytes) or not (32 < len(data) < 10_000_000):
                    continue
                dest = output / prefix / Path(name.replace("\\","/"))
                if ".." in dest.parts:
                    continue
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(data)
                print("PYINSTALLER_AUDIO",name,"bytes",len(data),"sha256",hashlib.sha256(data).hexdigest())
                with_audio.append(name)
            except Exception as exc:
                print("AUDIO_EXTRACT_ERROR",name,str(exc))
        count += 1
    return {"entries":count,"audio":with_audio}

def main():
    exe, output = Path(sys.argv[1]),Path(sys.argv[2])
    output.mkdir(parents=True,exist_ok=True)
    try:
        archive = CArchiveReader(str(exe))
    except Exception as exc:
        print("NOT_PYINSTALLER_ARCHIVE",exe.name,type(exc).__name__,str(exc))
        return 1
    result = dump(archive,output)
    print("PYINSTALLER_SCAN",exe.name,json.dumps(result,ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
