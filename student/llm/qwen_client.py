# student/llm/qwen_client.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from llama_cpp import Llama


class LocalQwenClient:
    """
    本地 GGUF 模型客户端（llama-cpp-python）
    - 单例持有模型（避免重复加载）
    - generate(prompt) 返回模型输出文本
    """

    def __init__(self, model_path: str | Path, n_ctx: int = 4096, n_threads: int = 8):
        self.model_path = Path(model_path).resolve()
        if not self.model_path.exists():
            raise FileNotFoundError(f"model not found: {self.model_path}")

        self.llm = Llama(
            model_path=str(self.model_path),
            n_ctx=n_ctx,
            n_threads=n_threads,
            verbose=False,
        )

    def generate(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.1,
        stop: Optional[list[str]] = None,
    ) -> str:
        out = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
        )
        return (out["choices"][0]["text"] or "").strip()
