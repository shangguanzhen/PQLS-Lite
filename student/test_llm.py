from llama_cpp import Llama

llm = Llama(
    model_path="models/qwen2.5-3b/qwen2.5-3b-instruct-q4_k_m.gguf",
    n_ctx=4096,
    n_threads=8,
    verbose=False
)

out = llm(
    "你是一个课程问答助手。学生问：什么是三视图？请用一句话回答。",
    max_tokens=128,
    temperature=0.2
)

print(out["choices"][0]["text"])
