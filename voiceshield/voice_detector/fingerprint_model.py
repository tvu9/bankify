#!/usr/bin/env python3
"""Report cached checkpoint and library versions. Does NOT download model weights."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--checkpoint',help='Local .pt file; omit to look up cached PellaV2 weights')
    ap.add_argument('--hash-weights',action='store_true',help='Hash ~2.32 GB checkpoint; may take time')
    ap.add_argument('--out')
    args=ap.parse_args()
    versions={}
    for lib in ('torch','torchaudio','transformers','huggingface-hub','numpy','scipy','soundfile'):
        try: versions[lib]=importlib.metadata.version(lib)
        except importlib.metadata.PackageNotFoundError: versions[lib]='unavailable'
    result={'model':'PellaV2','repo':'Sadanie/pellav2-audio-deepfake-detector',
            'weights_file':'pellav2_detector.pt','os':platform.system(),
            'architecture':platform.machine(),'python':platform.python_version(),
            'libraries':versions,'weights_cached':False,'weights_size_bytes':None,'sha256':None}
    weights=args.checkpoint
    if not weights:
        try:
            from huggingface_hub import hf_hub_download
            weights=hf_hub_download(result['repo'],filename=result['weights_file'],local_files_only=True)
        except Exception as exc:
            print(f'Local checkpoint not found: {type(exc).__name__}; no download attempted.')
    if weights:
        p=Path(weights).expanduser()
        if not p.is_file(): raise FileNotFoundError(weights)
        result['weights_cached']=True
        result['weights_size_bytes']=p.stat().st_size
        if args.hash_weights:
            digest=hashlib.sha256()
            with p.open('rb') as f:
                for buf in iter(lambda:f.read(4*1024*1024),b''): digest.update(buf)
            result['sha256']=digest.hexdigest()
    output=json.dumps(result,indent=2)
    print(output)
    if args.out:
        p=Path(args.out)
        if p.exists(): raise FileExistsError('Output already exists')
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(output+'\n')

if __name__=='__main__':main()
