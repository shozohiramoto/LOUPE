"""Benchmark v0.9.2 256^3 orthogonal preview on an actual CT series.

Example from the ZIP folder:
  py tools\benchmark_orthogonal_preview.py "D:\\CT\\rec\\rec00000.tif"

Runs once against an isolated temporary cache (forces cache build), then
verifies cached repeat. Does not modify source TIFFs.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from loupe.io import discover
from loupe.orthogonal.cache import build_preview, validate_ct_series


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('first_tiff',type=Path)
    ap.add_argument('--out',type=Path,help='Optional JSON results path')
    args=ap.parse_args()
    paths,_=discover(args.first_tiff)
    paths=validate_ct_series(paths)
    with tempfile.TemporaryDirectory(prefix='LOUPE_ortho_benchmark_') as tmp:
        start=time.perf_counter()
        meta,cache=build_preview(paths,root=tmp)
        build_sec=time.perf_counter()-start
        start=time.perf_counter()
        meta2,cache2=build_preview(paths,root=tmp)
        reuse_sec=time.perf_counter()-start
        assert cache==cache2 and meta==meta2
    result={'source':str(paths[0]),'count':len(paths),
            'preview_shape':meta['shape'],
            'preview_cache_mib':meta['shape'][0]*meta['shape'][1]*meta['shape'][2]*4/2**20,
            'first_build_seconds':round(build_sec,3),
            'cache_reuse_seconds':round(reuse_sec,3),
            'note':'Windows OS cache affects absolute timings; preview is not quantitative'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
