from llama_cpp import Llama
from llm.prompt import STUDENT_QA_PROMPT

llm = Llama(
    model_path="models/qwen2.5-3b/qwen2.5-3b-instruct-q4_k_m.gguf",
    n_ctx=4096,
    n_threads=8,
    verbose=False
)

question = "老师，这个地方我有点懵，三视图画的时候是不是一定要对齐啊？"

out = llm(
    STUDENT_QA_PROMPT + question,
    max_tokens=256,
    temperature=0.1
)

print(out["choices"][0]["text"])
