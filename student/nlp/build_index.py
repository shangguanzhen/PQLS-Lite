# student/nlp/build_index.py
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from datetime import datetime

import numpy as np


DEFAULT_INSTRUCTION = "Represent the question for retrieving relevant video segments:"


def load_questions_items(course_dir: Path):
    db = course_dir / "questions.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    try:
        # teacher端：questions(id, q, segment_filename, segment_idx, ...)
        cur.execute("SELECT q, segment_filename, segment_idx FROM questions ORDER BY id ASC")
        rows = cur.fetchall()
        out = []
        for q, seg, idx in rows:
            q = (q or "").strip()
            seg = (seg or "").strip()
            try:
                idx = int(idx) if idx is not None else -1
            except Exception:
                idx = -1
            if q and seg:
                out.append((q, seg, idx))
        return out
    finally:
        conn.close()


def list_courses(library_dir: Path):
    if not library_dir.exists():
        return []
    out = []
    for p in sorted(library_dir.iterdir()):
        if p.is_dir() and (p / "manifest.json").exists():
            out.append(p)
    return out


def _load_embedder(model_dir: Path):
    """
    兼容两种方式：
    1) InstructorEmbedding.INSTRUCTOR（最好，instructor系列原生）
    2) sentence_transformers.SentenceTransformer（兜底）
    """
    model_dir = model_dir.resolve()

    # 方案1：InstructorEmbedding（推荐）
    try:
        from InstructorEmbedding import INSTRUCTOR  # type: ignore

        model = INSTRUCTOR(str(model_dir))

        def encode(texts, instruction=DEFAULT_INSTRUCTION, batch_size=16):
            pairs = [[instruction, t] for t in texts]
            emb = model.encode(pairs, batch_size=batch_size, show_progress_bar=True, normalize_embeddings=True)
            return np.asarray(emb, dtype=np.float32)

        return encode, "InstructorEmbedding.INSTRUCTOR"

    except Exception:
        pass

    # 方案2：SentenceTransformer（兜底）
    from sentence_transformers import SentenceTransformer  # type: ignore

    model = SentenceTransformer(str(model_dir))

    def encode(texts, instruction=DEFAULT_INSTRUCTION, batch_size=32):
        # 有些ST版本支持 prompt_name / prompts，这里不强依赖，直接编码文本（兜底可用）
        emb = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        return np.asarray(emb, dtype=np.float32)

    return encode, "sentence_transformers.SentenceTransformer"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library_dir", required=True, help="学生端课程库目录（例如：C:\\Users\\...\\Desktop\\PQLS_Courses）")
    ap.add_argument("--model_dir", required=True, help="本地模型目录（例如：student/models/instructor-xl）")
    ap.add_argument("--out_dir", default="", help="索引输出目录（默认：student/nlp/index）")
    ap.add_argument("--batch_size", type=int, default=24)
    ap.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    args = ap.parse_args()

    library_dir = Path(args.library_dir).resolve()
    model_dir = Path(args.model_dir).resolve()

    if not library_dir.exists():
        raise SystemExit(f"library_dir 不存在：{library_dir}")
    if not model_dir.exists():
        raise SystemExit(f"model_dir 不存在：{model_dir}")

    script_dir = Path(__file__).resolve().parent
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (script_dir / "index")
    out_dir.mkdir(parents=True, exist_ok=True)

    course_dirs = list_courses(library_dir)
    records = []
    texts = []

    for cd in course_dirs:
        course_name = cd.name
        items = load_questions_items(cd)
        for q, seg, idx in items:
            records.append({
                "course_name": course_name,
                "course_dir": str(cd),
                "q": q,
                "seg": seg,
                "segment_idx": idx,
            })
            texts.append(q)

    if not records:
        raise SystemExit("没有可索引的条目（请确认课程库里有课程且 questions.db 非空）")

    encode, backend = _load_embedder(model_dir)
    print(f"[OK] embedder_backend = {backend}")
    print(f"[OK] indexing items = {len(records)}")

    emb = encode(texts, instruction=args.instruction, batch_size=args.batch_size)
    if emb.ndim != 2 or emb.shape[0] != len(records):
        raise SystemExit(f"embedding shape 异常：{emb.shape} vs records={len(records)}")

    # 写文件
    npy_path = out_dir / "embeddings.npy"
    rec_path = out_dir / "records.json"
    meta_path = out_dir / "index_meta.json"

    np.save(str(npy_path), emb)
    rec_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "library_dir": str(library_dir),
        "model_dir": str(model_dir),
        "backend": backend,
        "instruction": args.instruction,
        "count": len(records),
        "dim": int(emb.shape[1]),
        "files": {
            "embeddings": str(npy_path),
            "records": str(rec_path),
        }
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] index_dir = {out_dir}")
    print(f" - {npy_path.name}  ({npy_path.stat().st_size/1024/1024:.2f} MB)")
    print(f" - {rec_path.name}  ({rec_path.stat().st_size/1024:.2f} KB)")
    print(f" - {meta_path.name}")


if __name__ == "__main__":
    main()
