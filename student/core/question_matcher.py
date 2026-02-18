from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import List, Dict


# =========================
# 简单中文分词
# =========================

def tokenize(text: str) -> List[str]:
    if not text:
        return []

    zh_words = re.findall(r"[\u4e00-\u9fa5]{2,}", text)
    en_words = re.findall(r"[a-zA-Z0-9_]+", text)

    words = zh_words + en_words

    seen = set()
    result = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)

    return result


# =========================
# 主匹配函数
# =========================

def match_questions(course_dir: Path, question: str, top_k: int = 5) -> List[Dict]:

    question = question.strip()
    if not question:
        return []

    db_path = Path(course_dir) / "questions.db"
    if not db_path.exists():
        raise FileNotFoundError("questions.db 不存在")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("SELECT question, segment_file, keywords, weight FROM questions")
    rows = cur.fetchall()
    conn.close()

    query_terms = tokenize(question)

    scored = []

    for q_text, segment_file, keywords, weight in rows:
        score = 0

        q_text = q_text or ""
        keywords = keywords or ""

        # 问题文本匹配
        for t in query_terms:
            if t in q_text:
                score += 2

        # 关键词匹配
        for t in query_terms:
            if t in keywords:
                score += 1

        score *= int(weight or 1)

        if score > 0:
            scored.append({
                "question": q_text,
                "segment_file": segment_file,
                "score": score
            })

    # 按得分排序
    scored.sort(key=lambda x: x["score"], reverse=True)

    return scored[:top_k]
