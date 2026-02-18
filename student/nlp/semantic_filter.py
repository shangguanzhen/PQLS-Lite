# student/nlp/semantic_filter.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from .normalize import normalize_zh, tokenize

def _cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    na = float(np.linalg.norm(a) + 1e-9)
    nb = float(np.linalg.norm(b) + 1e-9)
    return float(np.dot(a, b) / (na * nb))

def _lexical_bonus(query_tokens: List[str], text: str) -> float:
    """词面命中加分：命中越多加分越高（封顶，避免压过语义）。"""
    if not query_tokens:
        return 0.0
    t = (text or "").lower()
    hit = 0
    for tok in query_tokens:
        if tok and tok in t:
            hit += 1
    return min(0.18, hit * 0.04)  # 命中1个+0.04，封顶0.18

class SemanticFilter:
    """
    独立语义检索器（用于验证模型“是否有作用”）。
    读取 build_index.py 产物：
      - index/embeddings.npy
      - index/records.json
      - index/index_meta.json
    """
    def __init__(self, index_dir: str, model_dir: str, device: Optional[str] = None):
        self.index_dir = Path(index_dir)
        self.model_dir = Path(model_dir)

        emb_path = self.index_dir / "embeddings.npy"
        rec_path = self.index_dir / "records.json"

        if not emb_path.exists():
            raise FileNotFoundError(f"missing embeddings.npy: {emb_path}")
        if not rec_path.exists():
            raise FileNotFoundError(f"missing records.json: {rec_path}")

        self.embeddings = np.load(str(emb_path))
        self.records: List[Dict[str, Any]] = json.loads(rec_path.read_text(encoding="utf-8"))

        # SentenceTransformer 会自动识别本地目录
        # device: "cuda" / "cpu" / None(自动)
        self.model = SentenceTransformer(str(self.model_dir), device=device)

    def search(
        self,
        query: str,
        topk: int = 30,
        course_name: Optional[str] = None,
        min_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        raw = query or ""
        q_norm = normalize_zh(raw)
        if not q_norm:
            return []

        q_tokens = tokenize(raw)

        q_emb = self.model.encode([q_norm], normalize_embeddings=False)[0].astype(np.float32)

        results = []
        for i, rec in enumerate(self.records):
            if course_name:
                cn = rec.get("course_name") or rec.get("course") or ""
                if cn != course_name:
                    continue

            text = rec.get("q") or rec.get("text") or rec.get("subtitle") or ""
            base = _cos_sim(q_emb, self.embeddings[i])
            bonus = _lexical_bonus(q_tokens, text)
            score = base + bonus

            if min_score is not None and score < min_score:
                continue

            out = dict(rec)
            out["score"] = float(score)
            results.append(out)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[: max(1, int(topk))]
