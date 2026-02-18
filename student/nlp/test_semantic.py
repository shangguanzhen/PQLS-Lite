# student/nlp/test_semantic.py
from __future__ import annotations

import argparse
from .semantic_filter import SemanticFilter

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index_dir", required=True, help="e.g. D:\\...\\student\\nlp\\index")
    ap.add_argument("--model_dir", required=True, help="e.g. D:\\...\\student\\models\\instructor-xl")
    ap.add_argument("--query", required=True, help="query text")
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--course", default=None, help="optional course_name filter")
    ap.add_argument("--device", default=None, help="cpu/cuda/None")
    args = ap.parse_args()

    sf = SemanticFilter(index_dir=args.index_dir, model_dir=args.model_dir, device=args.device)
    res = sf.search(args.query, topk=args.topk, course_name=args.course)

    print("=" * 80)
    print("query:", args.query)
    print("topk:", args.topk, "course:", args.course, "device:", args.device)
    print("-" * 80)

    for j, r in enumerate(res, 1):
        cn = r.get("course_name") or r.get("course") or ""
        seg = r.get("seg") or r.get("segment") or r.get("video") or ""
        text = r.get("q") or r.get("text") or r.get("subtitle") or ""
        print(f"[{j:02d}] score={r.get('score'):.4f}  course={cn}")
        print(f"     seg={seg}")
        print(f"     text={text}")

if __name__ == "__main__":
    main()
