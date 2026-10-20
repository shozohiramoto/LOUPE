"""Command line inspection, extraction and performance checks for HR engine.

Run from project root: python -m loupe.orthogonal.high_resolution_cli ...
"""
import argparse
import json
from pathlib import Path
import time
import os
import threading
from .high_resolution import extract_plane, scan_series


class _PeakMemory:
    """Optional process RSS sampling; reports None if psutil is not installed."""
    def __init__(self):
        self._stop = threading.Event()
        self.start_rss_mib = None
        self.peak_rss_mib = None
        self._thread = None
        try:
            import psutil
            self._proc = psutil.Process(os.getpid())
        except ImportError:
            self._proc = None

    def __enter__(self):
        if self._proc is not None:
            self.start_rss_mib = self._proc.memory_info().rss / (1024 * 1024)
            self.peak_rss_mib = self.start_rss_mib
            def sample():
                while not self._stop.wait(0.05):
                    try:
                        self.peak_rss_mib = max(self.peak_rss_mib, self._proc.memory_info().rss / (1024 * 1024))
                    except Exception:
                        return
            self._thread = threading.Thread(target=sample, name="loupe-memory-sampler", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if self._proc is not None:
            self.peak_rss_mib = max(self.peak_rss_mib, self._proc.memory_info().rss / (1024 * 1024))


def main(argv=None):
    parser = argparse.ArgumentParser(description="LOUPE high-resolution orthogonal CT TIFF engine")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "extract", "benchmark"):
        p = sub.add_parser(name)
        p.add_argument("ct", type=Path, help="CT folder or recNNNNN.tif")
        p.add_argument("--pixel-size-um", type=float, help="Verified in-plane pixel size; overrides TIFF header")
        if name != "inspect":
            p.add_argument("--plane", choices=("YZ", "ZX"), required=True)
            p.add_argument("--index", type=int, required=True, help="Fixed X for YZ, fixed Y for ZX (0-based)")
            p.add_argument("--z-start", type=int, default=0, help="Inclusive zero-based series position")
            p.add_argument("--z-stop", type=int, help="Exclusive zero-based series position")
            p.add_argument("--z-spacing-um", type=float, help="Verified Z spacing (otherwise assumes isotropic CT)")
            p.add_argument("--read-mode", choices=("auto", "memmap", "decode"), default="auto")
            p.add_argument("--output", type=Path, default=Path("LOUPE_Exports"))
    args = parser.parse_args(argv)
    start = time.perf_counter()
    print("Scanning TIFF headers...", flush=True)
    with _PeakMemory() as mem:
        series = scan_series(args.ct, pixel_size_um=args.pixel_size_um)
    print(json.dumps({"count":series.count,"shape_yx":series.shape,"dtype":series.dtype,
                      "index_range":[series.indices[0],series.indices[-1]],
                      "pixel_size_um":series.pixel_size_um,
                      "calibration_source":series.calibration_source,
                      "estimated_full_volume_gib":round(series.frame_bytes*series.count/(1024**3),3)}, indent=2))
    if args.command == "inspect":
        return 0
    last_pct = [-1]
    def report(done,total):
        pct=done*100//total
        if pct//5 != last_pct[0]//5:
            print(f"Processed {done}/{total} ({pct}%)",flush=True)
            last_pct[0]=pct
    with _PeakMemory() as mem:
        r=extract_plane(series,plane=args.plane,fixed_index=args.index,
                        z_start=args.z_start,z_stop=args.z_stop,output_dir=args.output,
                        z_spacing_um=args.z_spacing_um,read_mode=args.read_mode,on_progress=report)
    report_data = {"tiff":str(r.tiff_path),"json":str(r.metadata_path),
                   "output_shape":r.shape,"dtype":r.dtype,
                   "scan_plus_extraction_sec":round(time.perf_counter()-start,3),
                   "extraction_sec":round(r.elapsed_seconds,3),
                   "rss_before_extraction_mib":round(mem.start_rss_mib,2) if mem.start_rss_mib is not None else None,
                   "rss_peak_extraction_mib":round(mem.peak_rss_mib,2) if mem.peak_rss_mib is not None else None,
                   "rss_increment_peak_mib":round(mem.peak_rss_mib-mem.start_rss_mib,2) if mem.start_rss_mib is not None else None,
                   "read_mode":args.read_mode,
                   "input_frame_count":series.count,
                   "z_start":args.z_start,"z_stop":args.z_stop or series.count}
    if args.command == "benchmark":
        benchmark_path = r.tiff_path.with_suffix(".benchmark.json")
        benchmark_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
        report_data["benchmark_report"] = str(benchmark_path)
    print(json.dumps(report_data,indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
