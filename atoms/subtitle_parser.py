# atoms/subtitle_parser.py
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


class SubtitleParseError(ValueError):
    """字幕解析失败时抛出。"""


@dataclass(frozen=True)
class SubtitleItem:
    index: int
    start: float  # seconds
    end: float    # seconds
    text: str


_TIME_SRT = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{1,3})"
)
_TIME_VTT = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{1,3})"
)

_ARROW = re.compile(r"\s*-->\s*")


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    hh = int(h)
    mm = int(m)
    ss = int(s)
    mss = int(ms.ljust(3, "0"))  # 1-3 位补齐到毫秒
    return hh * 3600 + mm * 60 + ss + (mss / 1000.0)


def _parse_timecode(token: str) -> float:
    token = token.strip()

    m1 = _TIME_SRT.fullmatch(token)
    if m1:
        return _to_seconds(m1["h"], m1["m"], m1["s"], m1["ms"])

    m2 = _TIME_VTT.fullmatch(token)
    if m2:
        return _to_seconds(m2["h"], m2["m"], m2["s"], m2["ms"])

    raise SubtitleParseError(f"Invalid timecode: {token}")


def _strip_vtt_tags(text: str) -> str:
    # 简单清理 WEBVTT 常见标签，如 <c>, <v>, <i> 等
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def parse_subtitle_file(path: str) -> List[SubtitleItem]:
    """
    解析 .srt / .vtt 字幕文件，返回 SubtitleItem 列表。
    - 自动识别扩展名
    - 对 VTT 会剔除 WEBVTT 头与简单标签

    约定:
    - 忽略空行
    - 允许多行字幕文本合并为一段（用空格连接）
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"subtitle file not found: {p}")

    ext = p.suffix.lower()
    raw = p.read_text(encoding="utf-8", errors="ignore")
    lines = [ln.rstrip("\n\r") for ln in raw.splitlines()]

    if ext == ".vtt":
        lines = _preprocess_vtt(lines)
        return _parse_blocks(lines, vtt_mode=True)
    elif ext == ".srt":
        return _parse_blocks(lines, vtt_mode=False)
    else:
        raise SubtitleParseError(f"Unsupported subtitle type: {ext} (only .srt/.vtt)")


def _preprocess_vtt(lines: List[str]) -> List[str]:
    out: List[str] = []
    started = False
    for ln in lines:
        if not started:
            # 跳过 WEBVTT header / notes
            if ln.strip().upper().startswith("WEBVTT"):
                continue
            if ln.strip().startswith("NOTE"):
                continue
            # 空行后通常进入正文
            if ln.strip() == "":
                started = True
                continue
            # 有些 vtt 没空行，遇到时间轴再开始
            if "-->" in ln:
                started = True

        if started:
            out.append(ln)
    return out


def _parse_blocks(lines: List[str], vtt_mode: bool) -> List[SubtitleItem]:
    items: List[SubtitleItem] = []
    buf: List[str] = []

    def flush_block(block_lines: List[str]) -> None:
        if not block_lines:
            return
        # block 形态：
        # SRT:
        #   12
        #   00:00:01,000 --> 00:00:03,000
        #   text...
        #
        # VTT:
        #   00:00:01.000 --> 00:00:03.000
        #   text...
        #
        blk = [x for x in block_lines if x.strip() != ""]
        if not blk:
            return

        idx = None
        time_line = None
        text_lines: List[str] = []

        if "-->" in blk[0]:
            time_line = blk[0]
            text_lines = blk[1:]
        else:
            # 可能是 index 行
            if len(blk) >= 2 and "-->" in blk[1]:
                try:
                    idx = int(blk[0].strip())
                except Exception:
                    idx = None
                time_line = blk[1]
                text_lines = blk[2:]
            else:
                # 不符合规则，跳过
                return

        if not time_line:
            return

        start_s, end_s = _parse_time_range(time_line, vtt_mode=vtt_mode)
        text = " ".join([t.strip() for t in text_lines if t.strip() != ""]).strip()
        if vtt_mode:
            text = _strip_vtt_tags(text)

        if text == "":
            return

        items.append(
            SubtitleItem(
                index=idx if idx is not None else (len(items) + 1),
                start=start_s,
                end=end_s,
                text=text,
            )
        )

    for ln in lines:
        if ln.strip() == "":
            flush_block(buf)
            buf = []
        else:
            buf.append(ln)
    flush_block(buf)

    # 过滤异常时间段
    items = [it for it in items if it.end > it.start and it.start >= 0]
    return items


def _parse_time_range(time_line: str, vtt_mode: bool) -> Tuple[float, float]:
    # 允许 VTT 的设置字段：00:00:01.000 --> 00:00:03.000 align:start position:0%
    parts = _ARROW.split(time_line.strip(), maxsplit=1)
    if len(parts) != 2:
        raise SubtitleParseError(f"Invalid time range line: {time_line}")

    left = parts[0].strip()
    right = parts[1].strip()

    # right 可能带 settings，取第一个 token
    right_token = right.split()[0].strip()

    start_s = _parse_timecode(left)
    end_s = _parse_timecode(right_token)
    return start_s, end_s
