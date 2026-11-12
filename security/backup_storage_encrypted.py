"""Encrypted export of Supabase Storage objects to a user-controlled offsite path.

Requires requests, GPG, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the
backup machine's environment. Never bundle that key or upload unencrypted data.
This is not a disaster-recovery substitute for a validated restore exercise.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests

MAX_SINGLE_OBJECT=1024*1024*1024


def safe_path(*parts: str) -> str:
    if not parts or any(not p or p in ('.','..') or '\\' in p or '\x00' in p or '/' in p for p in parts):
        raise ValueError('Unsafe Storage object path')
    return '/'.join(parts)


def list_bucket_files(session:requests.Session, endpoint:str, bucket:str, prefix:str=''):
    """Walk object directory listing with explicit pagination."""
    offset=0
    while True:
        url=f'{endpoint}/storage/v1/object/list/{quote(bucket,safe="")}'
        response=session.post(url,json={'prefix':prefix,'limit':100,'offset':offset},timeout=30)
        if not response.ok:raise RuntimeError('Storage list failed; check key and bucket policies')
        rows=response.json()
        if not isinstance(rows,list):raise RuntimeError('Storage listing returned invalid JSON')
        for row in rows:
            name=row.get('name')
            if not isinstance(name,str):raise RuntimeError('Invalid object name')
            if name in ('','.','..') or '/' in name or '\\' in name:raise RuntimeError('Unsafe object name')
            object_path=(prefix + name).strip('/')
            if row.get('id') is None:
                yield from list_bucket_files(session,endpoint,bucket,object_path+'/')
            else:
                yield object_path,row
        if len(rows)<100:break
        offset+=100


def export_storage(recipient:str,destination:Path,buckets:list[str],env:dict[str,str]|None=None)->Path:
    config=dict(os.environ if env is None else env)
    url=config.get('SUPABASE_URL','').rstrip('/')
    token=config.get('SUPABASE_SERVICE_ROLE_KEY','')
    if not url.startswith('https://') or not token or len(token)<25:
        raise ValueError('SUPABASE_URL (HTTPS) and SUPABASE_SERVICE_ROLE_KEY required on backup machine')
    if not re.fullmatch(r'[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?',recipient):
        raise ValueError('Use a GPG recipient fingerprint')
    if not destination.is_dir() or not shutil.which('gpg'):
        raise ValueError('Destination must exist, GPG must be installed')
    if not buckets or any(not re.fullmatch(r'[a-zA-Z0-9_-]{1,120}',b) for b in buckets):
        raise ValueError('Specify safe bucket IDs')
    session=requests.Session()
    session.headers.update({'apikey':token,'Authorization':'Bearer '+token})
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=destination/f'DeiLaw-storage-{stamp}.tar.gpg'
    partial=destination/f'.{output.name}.incomplete'
    if output.exists() or partial.exists():raise FileExistsError('Refusing to overwrite backup')
    records=[]
    try:
        with tempfile.TemporaryFile() as error_stream:
            gpg=subprocess.Popen(['gpg','--batch','--yes','--encrypt','--recipient',recipient,
                                  '--output',str(partial)],stdin=subprocess.PIPE,stderr=error_stream)
            try:
                assert gpg.stdin is not None
                with tarfile.open(mode='w|',fileobj=gpg.stdin) as tar:
                    for bucket in buckets:
                        for path,meta in list_bucket_files(session,url,bucket):
                            members=path.split('/')
                            safe_path(*members)
                            endpoint=f'{url}/storage/v1/object/{quote(bucket,safe="")}/{quote(path,safe="/")}'
                            with session.get(endpoint,timeout=(15,120),stream=True) as response:
                                if not response.ok:raise RuntimeError('Storage object download failed')
                                claimed=(meta.get('metadata') or {}).get('size')
                                length=int(claimed or response.headers.get('Content-Length') or 0)
                                if not 0<length<=MAX_SINGLE_OBJECT:
                                    raise RuntimeError('Invalid Storage object size')
                                info=tarfile.TarInfo(safe_path('storage',bucket,*members))
                                info.size=length;info.mtime=int(datetime.now(timezone.utc).timestamp());info.mode=0o600
                                response.raw.decode_content=False
                                tar.addfile(info,response.raw)
                                records.append({'bucket':bucket,'path':path,'size_bytes':length})
                    body=json.dumps({'exported_at':stamp,'objects':records},ensure_ascii=False).encode('utf-8')
                    manifest=tarfile.TarInfo('backup_manifest.json');manifest.size=len(body);manifest.mode=0o600
                    tar.addfile(manifest,io.BytesIO(body))
                gpg.stdin.close()
                if gpg.wait()!=0:raise RuntimeError('GPG encryption failed')
            except BaseException:
                if gpg.stdin and not gpg.stdin.closed:gpg.stdin.close()
                if gpg.poll() is None:gpg.kill()
                gpg.wait();raise
        if not partial.exists() or partial.stat().st_size<100:raise RuntimeError('Encrypted archive missing')
        partial.replace(output)
    except BaseException:
        partial.unlink(missing_ok=True);raise
    with output.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    (destination/(output.name+'.json')).write_text(json.dumps({'name':output.name,'sha256':digest,
        'object_count':len(records),'created_at_utc':stamp},indent=2)+'\n',encoding='utf-8')
    print(f'Encrypted storage backup: {output}\nObjects: {len(records)}\nSHA256: {digest}')
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipient',required=True)
    parser.add_argument('--destination',required=True,type=Path)
    parser.add_argument('--bucket',action='append',required=True)
    args=parser.parse_args()
    export_storage(args.recipient,args.destination,args.bucket)
