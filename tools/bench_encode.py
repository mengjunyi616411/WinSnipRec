"""Measure the real CPU cost of the encoder settings WinSnipRec uses.

The lavfi frame generator is single-threaded and slow at large frame sizes, so
each measurement is taken twice -- once with the frames discarded (generator
only) and once through the encoder -- and the difference is reported.  That is
the actual encoder cost, in CPU-seconds per second of video (= cores needed for
realtime).

Run:  .venv\\Scripts\\python.exe tools\\bench_encode.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winsnip.core.encoder import ffmpeg_path  # noqa: E402

DURATION = 4
BENCH_RE = re.compile(r"bench: utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s")

STATIC = "smptebars=size={w}x{h}:rate={fps}"     # detailed but motionless frame
MOTION = "testsrc2=size={w}x{h}:rate={fps}"      # full motion, worst case


def cpu_of(args: list[str]) -> tuple[float, float]:
    command = [ffmpeg_path(), "-hide_banner", "-loglevel", "info", "-benchmark",
               *args, "-t", str(DURATION), "-f", "null", "-"]
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    wall = time.perf_counter() - started
    log = (result.stderr or "") + (result.stdout or "")
    match = BENCH_RE.search(log)
    cpu = (float(match.group(1)) + float(match.group(2))) if match else 0.0
    return cpu, wall


def encode_cost(source: str, encoder: list[str], pix_fmt: str = "yuv420p") -> tuple[float, float]:
    """(encoder CPU-seconds per second of video, encoder-only wall seconds)."""
    base_cpu, _ = cpu_of(["-f", "lavfi", "-i", source, "-c:v", "rawvideo", "-f", "null"])
    full_cpu, full_wall = cpu_of(["-f", "lavfi", "-i", source, *encoder,
                                  "-pix_fmt", pix_fmt, "-f", "null"])
    return max(0.0, (full_cpu - base_cpu) / DURATION), full_wall


def line(label: str, cores: float, extra: str = "") -> str:
    verdict = "✅ 富余" if cores < 1.5 else ("⚠️ 吃紧" if cores < 3.0 else
                                          ("❌ 低端机跑不动" if cores < 6 else "❌ 单机软编不现实"))
    return f"{label:26s} {cores:5.2f} 核  {verdict}{extra}"


def main() -> int:
    print(f"ffmpeg: {ffmpeg_path()}")
    print(f"每档 {DURATION} 秒，libx264 veryfast CRF20（程序默认）")
    print("数值 = 纯编码消耗的 CPU 秒 / 每秒视频（已扣除素材生成开销）\n")

    print("=== libx264 软编（CPU 编码，当前默认）===")
    for width, height, fps in ((1280, 720, 30), (1920, 1080, 30), (1920, 1080, 60),
                               (2560, 1440, 30), (3840, 2160, 30)):
        source = MOTION.format(w=width, h=height, fps=fps)
        cores, wall = encode_cost(source, ["-c:v", "libx264", "-preset", "veryfast",
                                           "-crf", "20"])
        print(line(f"{width}x{height}@{fps} 全动态", cores, f"  (全程 {wall:.1f}s)"))

    for width, height, fps in ((1920, 1080, 30), (1920, 1080, 60)):
        source = STATIC.format(w=width, h=height, fps=fps)
        cores, wall = encode_cost(source, ["-c:v", "libx264", "-preset", "veryfast",
                                           "-crf", "20"])
        print(line(f"{width}x{height}@{fps} 静止桌面", cores, f"  (全程 {wall:.1f}s)"))

    print("\n=== BGRA 输入（程序实际管道：抓屏原始帧 → 色彩转换 → 编码）===")
    source = MOTION.format(w=1920, h=1080, fps=30)
    base_cpu, _ = cpu_of(["-f", "lavfi", "-i", source, "-c:v", "rawvideo", "-f", "null"])
    full_cpu, _ = cpu_of(["-f", "lavfi", "-i", source, "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "20", "-f", "null"])
    yuv_cores = max(0.0, (full_cpu - base_cpu) / DURATION)
    bgra_cpu, _ = cpu_of(["-f", "lavfi", "-i", source, "-pix_fmt", "bgra",
                          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                          "-f", "null"])
    bgra_cores = max(0.0, (bgra_cpu - base_cpu) / DURATION)
    print(f"1080p30 yuv420p 输入          {yuv_cores:5.2f} 核")
    print(f"1080p30 bgra   输入（同程序） {bgra_cores:5.2f} 核"
          f"   → 色彩转换多耗 {bgra_cores - yuv_cores:.2f} 核")

    print("\n=== 硬件编码（同素材，含色彩转换）===")
    for encoder, tag in (("h264_nvenc", "NVIDIA NVENC"), ("h264_qsv", "Intel QuickSync"),
                         ("h264_mf", "MediaFoundation")):
        for width, height, fps in ((1920, 1080, 30), (1920, 1080, 60), (3840, 2160, 30)):
            source = MOTION.format(w=width, h=height, fps=fps)
            base_cpu, _ = cpu_of(["-f", "lavfi", "-i", source, "-c:v", "rawvideo",
                                  "-f", "null"])
            full_cpu, wall = cpu_of(["-f", "lavfi", "-i", source, "-c:v", encoder,
                                     "-b:v", "12M", "-f", "null"])
            cores = max(0.0, (full_cpu - base_cpu) / DURATION)
            print(line(f"{tag} {width}x{height}@{fps}", cores, f"  (全程 {wall:.1f}s)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
