# =========================
# 关键修复：确保能 import atoms
# =========================
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# =========================
# 标准库
# =========================
from datetime import datetime
from dataclasses import dataclass
import shutil
import re
import sqlite3
import json
import hashlib

# =========================
# 项目内模块
# =========================
from atoms.subtitle_parser import parse_subtitle_file
from atoms.lossless_cut import lossless_cut, LosslessCutError

# =========================
# 路径定义
# =========================
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"
BIN_DIR = PROJECT_ROOT / "bin"
FFMPEG_PATH = BIN_DIR / "ffmpeg.exe"


# =========================
# Run 上下文
# =========================
@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path
    source_dir: Path
    segments_dir: Path
    course_db_path: Path
    questions_db_path: Path


# =========================
# 文件名工具
# =========================
def safe_text(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "", text)
    return text.strip()

def short_text(text: str, max_len: int = 24) -> str:
    return text[:max_len]

def build_segment_filename(index: int, subtitle_text: str) -> str:
    name = short_text(safe_text(subtitle_text))
    if not name:
        name = "clip"
    return f"seg_{index:04d}_{name}.mp4"


# =========================
# Step 1：创建 run（支持 base_dir）
# =========================
def create_run(base_dir: Path | None = None) -> RunContext:
    """
    base_dir:
      - None  -> 使用默认 DATA_DIR / runs
      - Path  -> 使用 base_dir / runs
    """
    runs_root = RUNS_DIR if base_dir is None else (Path(base_dir) / "runs")
    runs_root.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = runs_root / run_id
    source_dir = run_dir / "source"
    segments_dir = run_dir / "segments"

    source_dir.mkdir(parents=True, exist_ok=True)
    segments_dir.mkdir(parents=True, exist_ok=True)

    course_db_path = run_dir / "course.db"
    questions_db_path = run_dir / "questions.db"

    return RunContext(
        run_id=run_id,
        run_dir=run_dir,
        source_dir=source_dir,
        segments_dir=segments_dir,
        course_db_path=course_db_path,
        questions_db_path=questions_db_path,
    )


# =========================
# Step 2：复制源文件到 source
# =========================
def copy_to_source(ctx: RunContext, video_path: Path, subtitle_path: Path) -> tuple[Path, Path]:
    video_path = Path(video_path)
    subtitle_path = Path(subtitle_path)

    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not subtitle_path.exists():
        raise FileNotFoundError(f"subtitle not found: {subtitle_path}")

    dst_video = ctx.source_dir / video_path.name
    dst_sub = ctx.source_dir / subtitle_path.name

    shutil.copy2(video_path, dst_video)
    shutil.copy2(subtitle_path, dst_sub)
    return dst_video, dst_sub


# =========================
# DB：course.db 初始化
# =========================
def _init_course_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idx INTEGER,
        filename TEXT,
        start REAL,
        end REAL,
        text TEXT
    )
    """)
    conn.commit()
    conn.close()


# =========================
# DB：questions.db 初始化
# =========================
def _init_questions_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        q TEXT,
        a TEXT,
        segment_filename TEXT,
        segment_idx INTEGER
    )
    """)
    conn.commit()
    conn.close()


# =========================
# ✅ 核心修复：从 course.db 的 segments 生成 questions.db
# =========================
def regenerate_questions_db_from_course_db(course_db: Path, questions_db: Path) -> int:
    """
    用 course.db/segments 生成 questions.db/questions
    返回插入条数
    """
    course_db = Path(course_db)
    questions_db = Path(questions_db)

    if not course_db.exists():
        raise FileNotFoundError(f"course.db not found: {course_db}")

    _init_questions_db(questions_db)

    conn_c = sqlite3.connect(str(course_db))
    cur_c = conn_c.cursor()
    cur_c.execute("SELECT idx, filename, text FROM segments ORDER BY idx ASC")
    rows = cur_c.fetchall()
    conn_c.close()

    conn_q = sqlite3.connect(str(questions_db))
    cur_q = conn_q.cursor()
    cur_q.execute("DELETE FROM questions")

    n = 0
    for idx, filename, text in rows:
        q = (text or "").strip()
        if not q:
            # 空字幕也可以跳过；你如果想“必须一一对应”，把 continue 去掉即可
            continue
        cur_q.execute(
            "INSERT INTO questions(q,a,segment_filename,segment_idx) VALUES(?,?,?,?)",
            (q, "", filename, int(idx) if idx is not None else None),
        )
        n += 1

    conn_q.commit()
    conn_q.close()
    return n


# =========================
# ✅ SubtitleItem / dict / tuple 统一适配
# =========================
def _normalize_sub_items(subs):
    """
    parse_subtitle_file(...) 可能返回：
      - dict: {"start":..., "end":..., "text":...}
      - tuple/list: (start, end, text)
      - SubtitleItem: obj.start / obj.end / obj.text
    输出统一为 [(start(float), end(float), text(str)), ...]
    """
    norm = []

    for s in subs:
        # 1) dict
        if isinstance(s, dict):
            start = float(s.get("start", 0))
            end = float(s.get("end", 0))
            text = str(s.get("text", "") or "").strip()
            norm.append((start, end, text))
            continue

        # 2) object with .start .end .text  (SubtitleItem)
        if hasattr(s, "start") and hasattr(s, "end"):
            try:
                start = float(getattr(s, "start", 0))
                end = float(getattr(s, "end", 0))
                text = str(getattr(s, "text", "") or "").strip()
                norm.append((start, end, text))
                continue
            except Exception:
                # 如果属性异常，继续走 tuple 兜底
                pass

        # 3) tuple/list
        try:
            start = float(s[0])
            end = float(s[1])
            text = str(s[2]).strip() if len(s) >= 3 else ""
            norm.append((start, end, text))
        except Exception:
            # 无法识别的项直接跳过
            continue

    return norm


# =========================
# Step 3：切分（写 course.db + 生成 questions.db）
# =========================
def build_segments(
    ctx: RunContext,
    input_video: Path,
    subtitle_file: Path,
    progress_callback=None,
) -> dict:
    """
    切分输出到 ctx.segments_dir
    同时写入：
      - course.db/segments
      - questions.db/questions（✅保证不为空）
    """
    if not FFMPEG_PATH.exists():
        raise FileNotFoundError(f"ffmpeg not found: {FFMPEG_PATH}")

    input_video = Path(input_video)
    subtitle_file = Path(subtitle_file)

    if not input_video.exists():
        raise FileNotFoundError(f"input video not found: {input_video}")
    if not subtitle_file.exists():
        raise FileNotFoundError(f"subtitle not found: {subtitle_file}")

    _init_course_db(ctx.course_db_path)

    subs = parse_subtitle_file(str(subtitle_file))

    # ✅ 修复点：兼容 SubtitleItem
    norm = _normalize_sub_items(subs)
    total = len(norm)

    conn = sqlite3.connect(str(ctx.course_db_path))
    cur = conn.cursor()
    cur.execute("DELETE FROM segments")

    ok_cnt = 0
    fail_cnt = 0

    for i, (start, end, text) in enumerate(norm, start=1):
        seg_name = build_segment_filename(i, text)
        out_path = ctx.segments_dir / seg_name

        try:
            lossless_cut(
                input_video=str(input_video),
                start_time=float(start),
                end_time=float(end),
                output_path=str(out_path),
                extra_args=[
                    "-hide_banner",
                    "-loglevel", "error"
                ],
            )
            ok_cnt += 1
        except LosslessCutError:
            fail_cnt += 1
            # 失败也写入 DB 便于追踪（可选）
            # continue

        cur.execute(
            "INSERT INTO segments(idx, filename, start, end, text) VALUES(?,?,?,?,?)",
            (i, seg_name, float(start), float(end), text),
        )
        conn.commit()

        if progress_callback:
            progress_callback(i, total)

    conn.close()

    # ✅ 关键：无条件用 course.db 生成 questions.db（保证不空）
    inserted = regenerate_questions_db_from_course_db(ctx.course_db_path, ctx.questions_db_path)

    return {
        "total": total,
        "ok": ok_cnt,
        "fail": fail_cnt,
        "course_db": str(ctx.course_db_path),
        "questions_db": str(ctx.questions_db_path),
        "questions_inserted": inserted,
        "segments_dir": str(ctx.segments_dir),
    }


# =========================
# manifest 写入
# =========================
def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def write_manifest(course_dir: Path, course_name: str):
    course_dir = Path(course_dir)

    def add_file(rel: str):
        p = course_dir / rel
        return {
            "path": rel.replace("\\", "/"),
            "size": p.stat().st_size,
            "sha256": _sha256_file(p),
        }

    files = []
    files.append(add_file("course.db"))
    files.append(add_file("questions.db"))

    # segments
    seg_dir = course_dir / "segments"
    for p in sorted(seg_dir.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(course_dir))
            files.append(add_file(rel))

    # source
    src_dir = course_dir / "source"
    for p in sorted(src_dir.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(course_dir))
            files.append(add_file(rel))

    manifest = {
        "manifest_version": 1,
        "course_name": course_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "generator": {
            "app": "PQLS-teacher",
            "ffmpeg": str(FFMPEG_PATH),
        },
        "layout": {
            "segments_dir": "segments",
            "source_dir": "source",
            "course_db": "course.db",
            "questions_db": "questions.db",
        },
        "files": files,
    }

    (course_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# =========================
# 导出课程包：到用户指定目录（默认桌面 PQLS_Courses）
# =========================
def export_course_package(ctx: RunContext, export_root: Path, course_name: str) -> Path:
    export_root = Path(export_root)
    export_root.mkdir(parents=True, exist_ok=True)

    out_dir = export_root / course_name
    if out_dir.exists():
        # 自动避让
        n = 2
        while True:
            c2 = export_root / f"{course_name} ({n})"
            if not c2.exists():
                out_dir = c2
                break
            n += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "segments").mkdir(exist_ok=True)
    (out_dir / "source").mkdir(exist_ok=True)

    # 拷贝 segments/source
    shutil.copytree(ctx.segments_dir, out_dir / "segments", dirs_exist_ok=True)
    shutil.copytree(ctx.source_dir, out_dir / "source", dirs_exist_ok=True)

    # 拷贝 course.db / questions.db（questions.db 已保证不空）
    shutil.copy2(ctx.course_db_path, out_dir / "course.db")
    shutil.copy2(ctx.questions_db_path, out_dir / "questions.db")

    # 写 manifest
    write_manifest(out_dir, course_name)

    # 写 meta（可选）
    meta = {
        "course_name": course_name,
        "imported_from": str(out_dir.resolve()),
        "validated": True
    }
    (out_dir / ".pqls_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return out_dir
