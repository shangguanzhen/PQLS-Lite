from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np


class SemanticSearcher:
    """
    混合召回检索器：
      1) 先做词面召回（token 命中/短语命中）构造候选集，保证“明显相关”的字幕一定进入候选
      2) 再用向量相似度排序（cosine）
    这样可以解决 embeddings 区分度不足导致 topK “随机”的问题。
    """

    def __init__(self, index_dir: Path, device: str = "cuda"):
        self.index_dir = Path(index_dir).resolve()
        self.emb_path = self.index_dir / "embeddings.npy"
        self.rec_path = self.index_dir / "records.json"
        self.meta_path = self.index_dir / "index_meta.json"

        if not self.emb_path.exists() or not self.rec_path.exists():
            raise FileNotFoundError(f"index 不完整：{self.emb_path} / {self.rec_path}")

        self.records = self._load_records(self.rec_path)
        self.emb = np.load(str(self.emb_path)).astype("float32")

        if len(self.records) != self.emb.shape[0]:
            raise ValueError(f"records 数量({len(self.records)}) != embeddings 行数({self.emb.shape[0]})")

        # 归一化：点积=cosine
        self.emb = self._l2norm(self.emb)

        self.device = device
        self.model = None
        self.model_dir: Optional[str] = None
        self._load_meta()

        # 预构建可检索文本缓存（避免每次循环都取 dict）
        self._texts = [self._text_of(r) for r in self.records]

    # ----------------- load helpers -----------------

    def _load_meta(self):
        if self.meta_path.exists():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                self.model_dir = meta.get("model_dir")
            except Exception:
                self.model_dir = None

    @staticmethod
    def _load_records(p: Path) -> List[Dict[str, Any]]:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k in ("records", "items", "data"):
                if k in data and isinstance(data[k], list):
                    return data[k]
            raise ValueError("records.json 格式不支持（不是 list，也没有 records/items/data）")
        if not isinstance(data, list):
            raise ValueError("records.json 不是 list")
        return data

    @staticmethod
    def _l2norm(x: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
        return x / n

    # ----------------- model -----------------

    def _lazy_model(self):
        if self.model is not None:
            return self.model
        from sentence_transformers import SentenceTransformer

        if not self.model_dir:
            raise RuntimeError("index_meta.json 未提供 model_dir，无法加载模型")

        self.model = SentenceTransformer(str(self.model_dir), device=self.device)
        return self.model

    def encode(self, text: str) -> np.ndarray:
        m = self._lazy_model()
        v = m.encode([text], normalize_embeddings=True)
        v = np.asarray(v, dtype="float32")
        if v.ndim == 1:
            v = v.reshape(1, -1)
        return v  # (1, D)

    # ----------------- fields -----------------

    @staticmethod
    def _text_of(r: Dict[str, Any]) -> str:
        # 你的 records.json 里常见是 q/text/subtitle
        return str(r.get("q") or r.get("text") or r.get("subtitle") or r.get("title") or "").strip()

    @staticmethod
    def _seg_of(r: Dict[str, Any]) -> str:
        return str(r.get("seg") or r.get("segment") or r.get("video") or "").strip()

    @staticmethod
    def _course_of(r: Dict[str, Any]) -> str:
        return str(r.get("course_name") or r.get("course") or "").strip()

    # ----------------- query normalize -----------------

    @staticmethod
    def _normalize_query(q: str) -> str:
        q = (q or "").strip()
        if not q:
            return ""
        # 轻量去口头词/虚词
        for w in (
            "的", "了", "呢", "啊", "呀", "吧", "嘛", "哦", "呃", "额",
            "其实", "应该", "首先", "然后", "就是", "似乎", "可能", "大概",
        ):
            q = q.replace(w, " ")
        q = " ".join(q.split())
        return q

    @staticmethod
    def _tokens(q_norm: str) -> List[str]:
        # 中文这里不做复杂分词：按空格 + 连续中文/字母数字片段
        if not q_norm:
            return []
        parts = []
        for p in q_norm.split():
            p = p.strip()
            if not p:
                continue
            parts.append(p)
        # 再提取连续片段（防止用户没空格）
        extra = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", q_norm)
        for e in extra:
            if e not in parts:
                parts.append(e)
        # 去掉过短 token
        parts = [t for t in parts if len(t) >= 2]
        return parts

    # ----------------- lexical recall -----------------

    def _lexical_candidates(self, q_norm: str, course_filter: Optional[str]) -> Set[int]:
        """
        词面召回候选：
          - token 命中
          - 紧凑短语命中（去空格）
        """
        toks = self._tokens(q_norm)
        if not toks:
            return set()

        q_compact = q_norm.replace(" ", "")
        cand: Set[int] = set()

        for i, txt in enumerate(self._texts):
            if not txt:
                continue
            if course_filter:
                if self._course_of(self.records[i]) != course_filter.strip():
                    continue

            hit = False
            if q_compact and q_compact in txt:
                hit = True
            else:
                # token 任意命中
                for t in toks:
                    if t and t in txt:
                        hit = True
                        break

            if hit:
                cand.add(i)

        return cand

    @staticmethod
    def _lex_bonus(q_norm: str, txt: str) -> float:
        if not q_norm or not txt:
            return 0.0
        q_compact = q_norm.replace(" ", "")
        bonus = 0.0
        # 紧凑短语强加分
        if q_compact and q_compact in txt:
            bonus += 0.20
        # token 命中加一点点
        toks = [t for t in q_norm.split() if t]
        hit = sum(1 for t in toks if t in txt)
        bonus += min(0.12, hit * 0.03)
        return bonus

    # ----------------- search -----------------

    def search(self, query: str, top_k: int = 50, course_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        q_norm = self._normalize_query(query)
        if not q_norm:
            return []

        # 1) 先词面召回候选，保证“明显相关”的句子进入候选
        lex_cand = self._lexical_candidates(q_norm, course_filter)

        # 2) 再用向量相似度取一批候选（兜底 + 扩展）
        qv = self.encode(q_norm)  # (1, D)
        scores = (self.emb @ qv.T).reshape(-1)

        # 取向量候选数量（越小越快，越大越稳）
        vec_k = min(max(top_k * 20, 200), len(self.records))
        vec_idx = np.argpartition(-scores, kth=vec_k - 1)[:vec_k]

        # 合并候选
        cand = set(vec_idx.tolist()) | set(lex_cand)

        # 3) 在候选集上做最终排序（cosine + lexical bonus）
        ranked = []
        for i in cand:
            r0 = self.records[int(i)]
            if course_filter:
                if self._course_of(r0) != course_filter.strip():
                    continue
            txt = self._texts[int(i)]
            base = float(scores[int(i)])
            bonus = self._lex_bonus(q_norm, txt)
            ranked.append((base + bonus, int(i)))

        ranked.sort(key=lambda x: x[0], reverse=True)

        out: List[Dict[str, Any]] = []
        for s, i in ranked[: max(1, int(top_k))]:
            r = dict(self.records[i])
            r["score"] = float(s)
            r["title"] = self._text_of(r)
            r["seg"] = self._seg_of(r)
            out.append(r)

        return out
