# atoms/lossless_cut.py
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

from atoms.ffmpeg_locator import ffmpeg_paths, FFmpegNotFoundError


class LosslessCutError(RuntimeError):
    pass


@dataclass
class LosslessCutResult:
    output_path: Path
    returncode: int
    cmd: list[str]


def _to_time_str(t: Union[int, float, str, None]) -> Optional[str]:
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return str(t)
    s = str(t).strip()
    return s if s else None


def _decode_bytes(b: bytes) -> str:
    """Decode subprocess output safely on Windows (avoid GBK crash)."""
    if not b:
        return ""
    # ffmpeg 通常输出 UTF-8；用 replace 保证永不抛异常
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        try:
            return b.decode("gbk", errors="replace")
        except Exception:
            return b.decode(errors="replace")


def lossless_cut(
    input_video: Union[str, Path] = None,
    output_path: Union[str, Path] = None,
    start_time: Union[int, float, str, None] = None,
    end_time: Union[int, float, str, None] = None,
    extra_args: Optional[Sequence[str]] = None,
    ffmpeg_path: Union[str, Path, None] = None,
    overwrite: bool = True,
    **kwargs,
) -> LosslessCutResult:
    """
    Stable API (recommended):
      lossless_cut(input_video=..., output_path=..., start_time=..., end_time=..., extra_args=[...])

    Compatibility:
      - accepts old parameter aliases via kwargs:
        - in_video / in_path / src / input
        - out / dst / output
        - ss / t_start
        - to / t_end
        - args
    """
    # --- compat mapping ---
    if input_video is None:
        input_video = kwargs.get("in_video") or kwargs.get("in_path") or kwargs.get("src") or kwargs.get("input")
    if output_path is None:
        output_path = kwargs.get("out") or kwargs.get("dst") or kwargs.get("output")
    if start_time is None:
        start_time = kwargs.get("ss") or kwargs.get("t_start")
    if end_time is None:
        end_time = kwargs.get("to") or kwargs.get("t_end")
    if extra_args is None:
        extra_args = kwargs.get("args")

    if input_video is None or output_path is None:
        raise LosslessCutError("lossless_cut requires input_video and output_path.")

    in_path = Path(input_video).resolve()
    out_path = Path(output_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ss = _to_time_str(start_time)
    to = _to_time_str(end_time)

    try:
        tools = ffmpeg_paths()
        ffmpeg = tools.ffmpeg
    except FFmpegNotFoundError as e:
        raise LosslessCutError(str(e)) from e

    if ffmpeg_path:
        ffmpeg = Path(ffmpeg_path).resolve()

    # ✅ 关键：加 -loglevel error / -nostats，让输出更少更稳定
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostats"]

    cmd += ["-y"] if overwrite else ["-n"]

    # -ss 放在 -i 前面：更快
    if ss is not None:
        cmd += ["-ss", ss]

    cmd += ["-i", str(in_path)]

    if to is not None:
        cmd += ["-to", to]

    cmd += ["-c", "copy"]

    if extra_args:
        cmd += list(extra_args)

    cmd += [str(out_path)]

    try:
        # ✅ 关键：不要 text=True（会触发 Windows 默认 GBK 解码线程崩溃）
        p = subprocess.run(cmd, capture_output=True, text=False)
    except Exception as e:
        raise LosslessCutError(f"Failed to run ffmpeg: {e}") from e

    if p.returncode != 0:
        stderr = _decode_bytes(p.stderr)
        raise LosslessCutError(
            "ffmpeg cut failed.\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr:\n{stderr}"
        )

    return LosslessCutResult(output_path=out_path, returncode=p.returncode, cmd=cmd)
