from __future__ import annotations

from pathlib import Path
from typing import Dict

from core.question_matcher import match_questions


class NavEngine:

    def __init__(self, top_k: int = 5):
        self.top_k = top_k

    def search(self, course_dir: Path, question: str) -> Dict:

        results = match_questions(
            course_dir=course_dir,
            question=question,
            top_k=self.top_k
        )

        return {
            "question": question,
            "results": results
        }


# =========================
# CLI 测试入口
# =========================

if __name__ == "__main__":

    BASE = Path(__file__).resolve().parents[1]
    COURSES_ROOT = BASE / "data" / "courses"

    print(f"[INFO] COURSES_ROOT : {COURSES_ROOT}")

    if not COURSES_ROOT.exists():
        raise FileNotFoundError("courses 目录不存在")

    course_dir = next((p for p in COURSES_ROOT.iterdir() if p.is_dir()), None)

    if not course_dir:
        raise FileNotFoundError("未找到课程目录")

    print(f"[INFO] Selected course: {course_dir.name}")

    engine = NavEngine(top_k=5)

    while True:
        q = input("\n请输入学生问题（回车退出）： ").strip()
        if not q:
            break

        resp = engine.search(course_dir=course_dir, question=q)

        print("\n====== 匹配结果 ======")
        for i, r in enumerate(resp["results"], 1):
            print(f"{i}. {r['question']}  →  {r['segment_file']}  (score={r['score']})")
