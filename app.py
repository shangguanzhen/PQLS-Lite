# -*- coding: utf-8 -*-
import sys
import io

# ===== Windows UTF-8 兜底 =====
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from flask import Flask, request, jsonify

from rewrite.rewriter import rewrite_question
from search.query import search_problem
from governance.judge import judge
from governance.hint_builder import build_hints
from governance.clarifier import build_clarify

# ✅ 不再猜函数名，直接导入模块
import governance.resolver as resolver

app = Flask(__name__)


@app.route("/query", methods=["POST"])
def query():
    data = request.get_json(silent=True) or {}

    original_question = data.get("question", "").strip()
    video_context = data.get("video_context")

    print("DEBUG question repr:", repr(original_question))

    if not original_question:
        return jsonify({"error": "question_required"}), 400

    # 0. rewrite
    rewrite_info = rewrite_question(original_question)
    effective_question = rewrite_info["rewritten"]

    # 1. search
    search_results = search_problem(effective_question, top_k=3)

    # 2. judge
    verdict = judge(search_results, video_context=video_context)

    response = {
        "question": original_question,
        "effective_question": effective_question,
        "rewrite": {
            "changed": rewrite_info["changed"],
            "reason": rewrite_info["reason"]
        },
        "verdict": verdict["level"],
        "reason": verdict["reason"]
    }

    # strong
    if verdict["level"] == "strong":
        response["result"] = verdict["top"]
        return jsonify(response)

    # weak
    if verdict["level"] == "weak":
        top = verdict["top"]
        response["result"] = top

        response["hints"] = build_hints(
            question=effective_question,
            result=top,
            video_context=video_context
        )

        clarify = build_clarify(
            question=effective_question,
            result=top,
            video_context=video_context
        )
        if clarify:
            response["clarify"] = clarify

        return jsonify(response)

    # no_match
    response["hints"] = build_hints(
        question=effective_question,
        result=search_results[0] if search_results else {},
        video_context=video_context
    )
    return jsonify(response)


@app.route("/resolve", methods=["POST"])
def resolve_route():
    """
    Stage 6：澄清选项 → 问题收敛
    """
    data = request.get_json(silent=True) or {}

    original_question = (data.get("question") or "").strip()
    choice = (data.get("choice") or "").strip()
    context = data.get("context") or {}

    if not original_question:
        return jsonify({"error": "question_required"}), 400
    if not choice:
        return jsonify({"error": "choice_required"}), 400

    # ✅ 关键：由 resolver 模块自己决定用哪个函数
    if hasattr(resolver, "resolve"):
        resolved_question = resolver.resolve(
            question=original_question,
            choice=choice,
            context=context
        )
    elif hasattr(resolver, "resolve_choice"):
        resolved_question = resolver.resolve_choice(
            question=original_question,
            choice=choice,
            context=context
        )
    else:
        # 最终兜底（永不报错）
        resolved_question = f"{original_question}（选择 {choice}）"

    return jsonify({
        "source_question": original_question,
        "choice": choice,
        "resolved_question": resolved_question
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
