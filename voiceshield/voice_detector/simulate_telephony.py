#!/usr/bin/env python3
"""Create offline telephony-channel audio variants, keeping original dataset split IDs.

Profiles: narrowband, noise10, g711u, opus16. Real G.711 and Opus use ffmpeg.
"""
import argparse
import csv
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from scipy.signal import butter, sosfiltfilt, resample_poly
import soundfile as sf
try:
    from .v3_common import read_manifest, load_audio, FIELDS, write_csv
except ImportError:
    from v3_common import read_manifest, load_audio, FIELDS, write_csv


def narrowband(x):
    if len(x) < 256: raise ValueError('Clip too short for bandpass filter')
    sos=butter(4,[300,3400],btype='bandpass',fs=16000,output='sos')
    y=sosfiltfilt(sos,x).astype(np.float32)
    return resample_poly(resample_poly(y,1,2),2,1).astype(np.float32)


def noise_at_snr(x,seed=42,snr_db=10):
    rng=np.random.default_rng(seed)
    rms=float(np.sqrt(np.mean(x*x)))
    if rms < 1e-8: return x.copy()
    noise=rng.standard_normal(len(x)).astype(np.float32)
    noise*=rms/(10**(snr_db/20)*np.sqrt(np.mean(noise*noise)))
    return np.clip(x+noise,-1,1).astype(np.float32)


def codec(x,profile):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg: raise RuntimeError('ffmpeg missing; install ffmpeg for real G.711/Opus codec tests')
    with tempfile.TemporaryDirectory(prefix='voiceshield_codec_') as d:
        base=Path(d); raw=base/'raw.wav'
        # above Path / concatenation done below for portability
        encoded=base/('encoded.wav' if profile=='g711u' else 'encoded.ogg')
        output=base/'decoded.wav'
        sf.write(raw,x,16000,subtype='PCM_16')
        if profile=='g711u':
            command=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(raw),
                     '-ac','1','-ar','8000','-af','highpass=f=300,lowpass=f=3400',
                     '-c:a','pcm_mulaw',str(encoded)]
        elif profile=='opus16':
            command=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(raw),
                     '-ac','1','-ar','48000','-c:a','libopus','-application','voip',
                     '-b:a','16k',str(encoded)]
        else: raise ValueError(profile)
        for args in [command,[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                              '-i',str(encoded),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(output)]]:
            p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
            if p.returncode: raise RuntimeError(p.stderr.decode(errors='replace')[-500:])
        y,rate=sf.read(output,dtype='float32')
        if rate!=16000: raise RuntimeError('Bad decoded sample rate')
        return np.ascontiguousarray(y)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True)
    p.add_argument('--out-dir',required=True)
    p.add_argument('--profiles',default='narrowband,noise10,g711u,opus16')
    p.add_argument('--split',choices=['train','val','test'],default=None)
    p.add_argument('--seed',type=int,default=2026)
    args=p.parse_args()
    selected=[v.strip() for v in args.profiles.split(',') if v.strip()]
    if not selected or len(selected)!=len(set(selected)) or any(s not in ('narrowband','noise10','g711u','opus16') for s in selected):
        p.error('Invalid/repeated profile')
    if any(s in ('g711u','opus16') for s in selected) and not shutil.which('ffmpeg'):
        p.error('ffmpeg is required for genuine G.711/Opus codec simulations; use --profiles narrowband,noise10 or install ffmpeg')
    rows=read_manifest(args.manifest)
    out=Path(args.out_dir).expanduser().resolve()
    if out.exists(): p.error('Output directory exists; choose a new directory (no overwrites)')
    out.mkdir(parents=True)
    results=[]
    try:
        (out/'audio').mkdir()
        for n,row in enumerate(rows):
            if args.split and row['split']!=args.split: continue
            x=load_audio(row['_resolved_path'])
            for profile in selected:
                if profile=='narrowband': y=narrowband(x)
                elif profile=='noise10': y=noise_at_snr(x,args.seed+n)
                else: y=codec(x,profile)
                key=hashlib.sha256(f'{row["sample_id"]}:{n}'.encode()).hexdigest()[:10]
                file=f'{n:05d}_{key}_{profile}.wav'
                sf.write(out/'audio'/file,y,16000,subtype='PCM_16')
                record={k:row.get(k,'') for k in FIELDS}
                record.update(sample_id=f'{row["sample_id"]}__{profile}',path=f'audio/{file}',
                              channel=profile)
                results.append(record)
        if not results: raise ValueError('No matching source clips')
        write_csv(out/'manifest.csv',results,FIELDS)
    except Exception:
        # Preserve any partial outputs for inspection; don't silently call them valid.
        raise
    print(f'Created {len(results)} augmented clips in {out}. Keep recordings outside Git.')
    print(f'Evaluate with: python voice_detector/evaluate_dataset.py --manifest "{out}/manifest.csv" --split test --out "{out}/test_scores.csv"')

if __name__=='__main__':main()
