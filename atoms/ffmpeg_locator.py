# atoms/ffmpeg_locator.py
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FFmpegPaths:
    project_root: Path
    ffmpeg: Path
    ffprobe: Path
    ffplay: Path


class FFmpegNotFoundError(RuntimeError):
    pass


def _find_project_root(start: Path | None = None) -> Path:
    """
    Find project root by walking upward and locating /bin/ffmpeg.exe (Windows),
    or /bin/ffmpeg (Linux/macOS). This makes it stable regardless of cwd.
    """
    start = (start or Path(__file__).resolve()).resolve()

    # Check parents including self directory
    for p in [start] + list(start.parents):
        bin_dir = p / "bin"
        if os.name == "nt":
            if (bin_dir / "ffmpeg.exe").exists():
                return p
        else:
            if (bin_dir / "ffmpeg").exists():
                return p

    # Fallback: try typical structure markers
    for p in [start] + list(start.parents):
        if (p / "atoms").is_dir() and (p / "teacher").is_dir():
            # not perfect, but better than nothing
            return p

    # As last resort, use cwd (not recommended)
    return Path.cwd().resolve()


def ffmpeg_paths(
    project_root: Path | None = None,
    allow_path_fallback: bool = True,
) -> FFmpegPaths:
    """
    Return absolute paths of ffmpeg/ffprobe/ffplay.
    Priority:
      1) <project_root>/bin/*
      2) PATH lookup (optional)
    """
    root = (project_root or _find_project_root()).resolve()
    bin_dir = root / "bin"

    if os.name == "nt":
        ffmpeg = bin_dir / "ffmpeg.exe"
        ffprobe = bin_dir / "ffprobe.exe"
        ffplay = bin_dir / "ffplay.exe"
    else:
        ffmpeg = bin_dir / "ffmpeg"
        ffprobe = bin_dir / "ffprobe"
        ffplay = bin_dir / "ffplay"

    # Primary: project bin
    if ffmpeg.exists() and ffprobe.exists() and ffplay.exists():
        return FFmpegPaths(root, ffmpeg, ffprobe, ffplay)

    # Optional fallback: PATH
    if allow_path_fallback:
        f1 = shutil.which("ffmpeg")
        f2 = shutil.which("ffprobe")
        f3 = shutil.which("ffplay")
        if f1 and f2 and f3:
            return FFmpegPaths(
                root,
                Path(f1).resolve(),
                Path(f2).resolve(),
                Path(f3).resolve(),
            )

    # Fail with clear message
    missing = []
    if not ffmpeg.exists():
        missing.append(ffmpeg.name)
    if not ffprobe.exists():
        missing.append(ffprobe.name)
    if not ffplay.exists():
        missing.append(ffplay.name)

    raise FFmpegNotFoundError(
        "FFmpeg tools not found.\n"
        f"Expected in: {bin_dir}\n"
        f"Missing: {', '.join(missing)}\n"
        "Fix: put ffmpeg/ffprobe/ffplay into <project_root>/bin/"
    )
