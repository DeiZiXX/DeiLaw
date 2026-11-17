"""Record a deterministic SHA256 binary inventory and installed package metadata.

NOT a third-party license audit. The output must be reviewed against
THIRD_PARTY_NOTICES.md before a SignPath release.
"""
from __future__ import annotations
import hashlib
import json
import sys
from importlib import metadata
from pathlib import Path


def inventory(source: Path):
    if not source.is_dir():
        raise FileNotFoundError(source)
    files = []
    for path in sorted(p for p in source.rglob('*') if p.is_file()):
        files.append({
            'path': path.relative_to(source).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'size': path.stat().st_size,
        })
    packages = []
    for dist in metadata.distributions():
        name = dist.metadata.get('Name')
        if name:
            packages.append({'name':name,'version':dist.version,
                             'license_expression':dist.metadata.get('License-Expression') or 'REVIEW REQUIRED'})
    packages.sort(key=lambda p: p['name'].lower())
    return {'kind':'UNSIGNED_BUILD_INVENTORY_NOT_LICENSE_CERTIFICATION',
            'files':files,'python_packages':packages}


def main():
    if len(sys.argv)!=3:
        raise SystemExit('Usage: build_inventory.py INPUT_DIRECTORY OUTPUT.json')
    src,out=map(Path,sys.argv[1:])
    out.parent.mkdir(parents=True,exist_ok=True)
    data=inventory(src)
    out.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Inventory:',len(data['files']),'files,',len(data['python_packages']),'packages')

if __name__=='__main__':
    main()
