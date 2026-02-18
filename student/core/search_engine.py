# student/core/search_engine.py
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import List, Tuple


# =========================
# 中文分词（轻量规则版）
# =========================

def tokenize(text: str) -> List[str]:
    """
    轻量中文拆词：
    - 保留 2 字以上中文
    - 保留英文
    - 去重
    """
    if not text:
        return []

    # 取中文连续字符
    zh_words = re.findall(r"[\u4e00-\u9fa5]{2,}", text)

    # 英文/数字
    en_words = re.findall(r"[a-zA-Z0-9_]+", text)

    words = zh_words + en_words

    # 去重
    seen = set()
    result = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)

    return result


# =========================
# 探测数据库结构
# =========================

def detect_schema(db_path: Path) -> Tuple[str, str, str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    if not tables:
        conn.close()
        raise RuntimeError("数据库没有表")

    table = tables[0]

    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]

    text_col = None
    file_col = None

    for c in cols:
        cl = c.lower()
        if cl in ["subtitle", "text", "content", "transcript"]:
            text_col = c
        if cl in ["filename", "file", "path", "video"]:
            file_col = c

    if not text_col:
        text_col = cols[0]
    if not file_col:
        file_col = cols[0]

    conn.close()
    return table, text_col, file_col


# =========================
# 强化召回主函数
# =========================

def search_videos(
    course_dir: Path,
    normalized_question: str,
    keywords: List[str],
    top_k: int = 5,
    original_question: str = "",
) -> List[Path]:

    course_dir = Path(course_dir)
    db_path = course_dir / "course.db"
    seg_dir = course_dir / "segments"

    if not db_path.exists():
        raise FileNotFoundError("course.db 不存在")

    table, text_col, file_col = detect_schema(db_path)

    # =========================
    # 生成召回词集合
    # =========================

    terms = []

    # 原始问题参与召回
    terms.extend(tokenize(original_question))

    # 规范问题参与召回
    terms.extend(tokenize(normalized_question))

    # 模型关键词参与召回
    for kw in keywords:
        terms.extend(tokenize(kw))

    # 去重
    seen = set()
    final_terms = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            final_terms.append(t)

    if not final_terms:
        return []

    # =========================
    # SQL LIKE 查询
    # =========================

    where_clause = " OR ".join([f"{text_col} LIKE ?" for _ in final_terms])
    sql = f"SELECT {file_col}, {text_col} FROM {table} WHERE {where_clause}"

    params = [f"%{t}%" for t in final_terms]

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    # =========================
    # 简单评分排序
    # =========================

    scored = []

    for fname, subtitle in rows:
        score = 0
        subtitle = subtitle or ""

        for t in final_terms:
            if t in subtitle:
                score += 1

        video_path = seg_dir / Path(fname).name
        scored.append((score, video_path))

    # 按分数排序
    scored.sort(key=lambda x: x[0], reverse=True)

    # 去重输出
    results = []
    seen_path = set()

    for score, p in scored:
        if p.exists() and str(p) not in seen_path:
            seen_path.add(str(p))
            results.append(p)

        if len(results) >= top_k:
            break

    return results
