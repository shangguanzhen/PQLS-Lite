# student/nlp/normalize.py
from __future__ import annotations
import re

# 可按需继续追加
STOPWORDS_ZH = {
    "似乎","应该","首先","然后","接着","之后","现在","其实","就是","的话","一下",
    "我们","你们","他们","大家","我","你","他","她","它","这","那","这个","那个","这些","那些",
    "怎么","如何","为什么","请问","麻烦","能不能","可以","是否","有没有","是不是",
    "有点","感觉","可能","大概","基本","一般","通常","主要",
    "请","帮我","帮忙","给我","告诉我","说一下","讲一下",
    "呃","额","嗯","啊","呀","呢","嘛","吧","么","哈","喔","哦",
}

_PUNCT = r"[，。！？、；：…（）()【】\[\]“”\"\'\t\r\n]"

def normalize_zh(text: str) -> str:
    """将输入净化为更适合语义检索/关键词回退的形式。"""
    t = (text or "").strip().lower()
    if not t:
        return ""
    t = re.sub(_PUNCT, " ", t)

    # 常见单字虚词
    for ch in ("的", "了", "着", "呢", "啊", "呀", "吧", "嘛", "哦"):
        t = t.replace(ch, " ")

    # 停用词（词组）
    for w in STOPWORDS_ZH:
        t = t.replace(w, " ")

    t = " ".join(t.split())
    return t

def tokenize(text: str) -> list[str]:
    t = normalize_zh(text)
    return [x for x in t.split(" ") if x]
