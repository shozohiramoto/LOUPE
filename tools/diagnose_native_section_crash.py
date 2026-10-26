"""ID098-18 headless Windows diagnostic (no Qt, no changes to source TIFFs).

Usage: python tools/diagnose_native_section_crash.py "CT_FOLDER_OR_REC_FILE" [--full]
By default, test 24 slices in both mmap and decoded modes.
The output goes under %%TEMP%%. Share only probe_summary.json + probe_progress.jsonl.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import faulthandler
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

# Permit calling this script from the project root or by full path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description="LOUPE Native Section engine isolation test")
    parser.add_argument("dataset", type=Path, help="CT reconstruction folder or one recNNNNN.tif")
    parser.add_argument("--full", action="store_true", help="Test all Z slices instead of 24 (may take time)")
    a = parser.parse_args()
    out = Path(tempfile.mkdtemp(prefix="LOUPE_native_probe_"))
    progress = out / "probe_progress.jsonl"
    result_path = out / "probe_summary.json"
    fault = open(out / "python_fault_trace.log", "w", encoding="utf-8")
    try:
        faulthandler.enable(file=fault, all_threads=True)
    except Exception:
        pass
    summary = {"tool":"LOUPE ID098-18 Native Section probe", "status":"STARTED", "modes":[], "full_test":a.full}

    def note(stage, **kwargs):
        entry = {"utc":datetime.now(timezone.utc).isoformat(),"stage":stage, **kwargs}
        with progress.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        print(stage, kwargs, flush=True)

    def save():
        tmp = result_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2),encoding="utf-8")
        os.replace(tmp,result_path)

    print("Result folder:", out, flush=True)
    save()
    try:
        from loupe.orthogonal.high_resolution import scan_series, extract_plane
        import tifffile
        from numpy import array_equal
        t0=time.perf_counter()
        note("scan.begin")
        series=scan_series(a.dataset)
        summary["series"]={"n_slices":series.count,"source_yx":series.shape,"dtype":series.dtype,
                           "xy_pixel_calibrated":series.pixel_size_um is not None}
        summary["scan_seconds"]=round(time.perf_counter()-t0,3)
        n=series.count if a.full else min(series.count,24)
        note("scan.done",slices=series.count,shape=series.shape,dtype=series.dtype,trial_slices=n)
        save()
        # Compare identical sections using two independent read paths.
        for mode in ("memmap","decode"):
            record={"mode":mode,"status":"STARTED"}
            summary["modes"].append(record);save()
            fixed_index=series.width//2
            note("extract.start",mode=mode,slices=n)
            t0=time.perf_counter()
            last_p=[0]
            def cb(done,total):
                if done==1 or done==total or done-last_p[0]>=max(1,total//4):
                    note("extract.progress",mode=mode,completed=done,total=total)
                    last_p[0]=done
            result=extract_plane(series,plane="YZ",fixed_index=fixed_index,z_start=0,z_stop=n,
                                 read_mode=mode,output_dir=out,output_prefix="PROBE",
                                 on_progress=cb)
            record["extract_seconds"]=round(time.perf_counter()-t0,3)
            note("read_tiff.start",mode=mode)
            arr=tifffile.imread(result.tiff_path)
            record["output_yx"]=arr.shape
            record["dtype"]=str(arr.dtype)
            # Test representative source pixels independently from TIFF decode.
            matches=[]
            for k in sorted({0, n//2, n-1}):
                src=tifffile.imread(series.paths[k])
                matches.append(bool(array_equal(arr[k],src[:,fixed_index])))
                del src
            record["pixel_checks_all_equal"]=all(matches)
            record["status"]="PASS" if all(matches) else "PIXEL_MISMATCH"
            note("mode.done",mode=mode,status=record["status"],seconds=record["extract_seconds"])
            del arr
            for p in (result.tiff_path,result.metadata_path):
                p.unlink(missing_ok=True)
            save()
        summary["status"]="PASS" if all(x["status"]=="PASS" for x in summary["modes"]) else "FAIL"
        note("all.done",status=summary["status"])
    except BaseException as exc:
        summary["status"]="FAIL"
        summary["error_type"]=type(exc).__name__
        summary["error_message"]=str(exc)[:1000]
        note("error",exception=type(exc).__name__,message=str(exc)[:300])
        traceback.print_exc()
    finally:
        save()
        fault.flush()
        fault.close()
        print("Report:",result_path, flush=True)
        print("Progress:",progress, flush=True)
    return 0 if summary["status"]=="PASS" else 1


if __name__=='__main__':
    raise SystemExit(main())
