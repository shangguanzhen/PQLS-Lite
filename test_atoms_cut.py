from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from atoms.subtitle_parser import parse_subtitle_file
from atoms.lossless_cut import lossless_cut

FFMPEG = ROOT / "bin" / "ffmpeg.exe"

subs = parse_subtitle_file(str(ROOT / "samples" / "demo.srt"))
print("subs:", len(subs), subs[0])

first = subs[0]

out = lossless_cut(
    video_path=str(ROOT / "samples" / "demo.mp4"),
    start_time=first.start,
    end_time=first.end,
    output_path=str(ROOT / "tmp" / "seg_0001.mp4"),
    ffmpeg_path=str(FFMPEG),   # 👈 关键
)

print("cut ok:", out.output_path)
