from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import List, Tuple


# =========================
# 动词规则（可扩展）
# =========================

ACTION_VERBS = [
    "画", "添加", "删除", "使用", "进入",
    "退出", "点击", "选择", "设置",
    "调整", "创建", "编辑", "修改"
]


# =========================
# 简单字幕过滤规则
# =========================

def is_valid_subtitle(text: str) -> bool:
    if not text:
        return False

    text = text.strip()

    # 长度限制
    if len(text) < 4 or len(text) > 30:
        return False

    # 必须包含操作动词
    if not any(v in text for v in ACTION_VERBS):
        return False

    return True


# =========================
# 生成问题文本
# =========================

def generate_question(text: str) -> str:
    text = text.strip()

    if text.endswith("。"):
        text = text[:-1]

    return f"如何{text}？"


# =========================
# 自动探测 course.db 结构
# =========================

def detect_schema(db_path: Path) -> Tuple[str, str, str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    if not tables:
        conn.close()
        raise RuntimeError("course.db 没有表")

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
# 构建 questions.db
# =========================

def build_questions(course_dir: Path):
    course_dir = Path(course_dir)

    course_db = course_dir / "course.db"
    if not course_db.exists():
        raise FileNotFoundError("course.db 不存在")

    questions_db = course_dir / "questions.db"

    print(f"[INFO] course.db   : {course_db}")
    print(f"[INFO] questions.db: {questions_db}")

    table, text_col, file_col = detect_schema(course_db)

    conn_course = sqlite3.connect(str(course_db))
    cur_course = conn_course.cursor()

    cur_course.execute(f"SELECT {file_col}, {text_col} FROM {table}")
    rows = cur_course.fetchall()
    conn_course.close()

    # 创建 questions.db
    conn_q = sqlite3.connect(str(questions_db))
    cur_q = conn_q.cursor()

    cur_q.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            segment_file TEXT NOT NULL,
            keywords TEXT,
            weight INTEGER DEFAULT 1
        )
    """)

    inserted = 0
    seen_questions = set()

    for segment_file, subtitle in rows:
        if not subtitle:
            continue

        subtitle = subtitle.strip()

        if not is_valid_subtitle(subtitle):
            continue

        question = generate_question(subtitle)

        if question in seen_questions:
            continue

        seen_questions.add(question)

        keywords = subtitle  # 第一版简单等于原字幕

        cur_q.execute("""
            INSERT INTO questions (question, segment_file, keywords, weight)
            VALUES (?, ?, ?, ?)
        """, (question, segment_file, keywords, 1))

        inserted += 1

    conn_q.commit()
    conn_q.close()

    print(f"[INFO] 插入问题数量: {inserted}")
    print("[DONE] questions.db 构建完成")


# =========================
# CLI 入口
# =========================

if __name__ == "__main__":
    BASE = Path(__file__).resolve().parents[1]
    COURSES_ROOT = BASE / "data" / "courses"

    print(f"[INFO] COURSES_ROOT: {COURSES_ROOT}")

    if not COURSES_ROOT.exists():
        raise FileNotFoundError("courses 目录不存在")

    course_dir = next((p for p in COURSES_ROOT.iterdir() if p.is_dir()), None)
    if not course_dir:
        raise FileNotFoundError("未找到课程目录")

    print(f"[INFO] Selected course: {course_dir.name}")

    build_questions(course_dir)
