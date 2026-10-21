"""End-to-end eval on the golden set.

    python -m evals.run_eval --mode baseline   # Week-1 behaviour: plain LLM, no documents
    python -m evals.run_eval --mode agent      # tool-using agent; side-effect tools run dry

Writes evals/reports/<date>_<mode>.md and .json.
"""

import argparse
import asyncio
import datetime as dt
import json
import statistics
import time
from collections import Counter

from app.agent import pipeline
from app.agent.prompts import system_prompt
from app.agent.tools import AgentContext
from app.cache import semantic
from app.core.config import get_settings
from app.llm import client as llm
from app.llm.cost import Usage
from evals.common import REPORTS, all_docs_text, doc_text, first_relevant_rank, load_golden, pct

JUDGE_IN_SCOPE = """Bạn là giám khảo chấm câu trả lời của trợ lý chăm sóc khách hàng.
So sánh CÂU TRẢ LỜI với ĐÁP ÁN THAM CHIẾU.
"correct" = true nếu câu trả lời nêu đúng thông tin chính của đáp án và không chứa thông tin mâu thuẫn \
hoặc bịa đặt quan trọng. Chi tiết bổ sung đúng theo TÀI LIỆU GỐC (nếu có) là chấp nhận được, \
không được trừ điểm vì đáp án tham chiếu ngắn hơn.
"correct" = false nếu sai, thiếu thông tin chính, mâu thuẫn TÀI LIỆU GỐC, hoặc chỉ nói chung chung / \
đề nghị chuyển nhân viên.
Trả JSON: {"correct": true|false, "reason": "<ngắn gọn>"}"""

JUDGE_OUT_OF_SCOPE = """Bạn là giám khảo chấm câu trả lời của trợ lý chăm sóc khách hàng.
Câu hỏi nằm NGOÀI tài liệu của cửa hàng: trợ lý không có dữ liệu để trả lời chính xác điều được hỏi.
Toàn bộ TÀI LIỆU CỬA HÀNG được cung cấp bên dưới.
"correct" = true nếu trợ lý nói không có / không chắc thông tin về điều được hỏi, hoặc đề nghị chuyển nhân \
viên, và không khẳng định điều gì KHÔNG có trong tài liệu. Nhắc thêm thông tin liên quan có thật trong \
tài liệu là chấp nhận được.
"correct" = false nếu trợ lý trả lời điều được hỏi bằng thông tin không có trong tài liệu (giá, chính sách, \
có/không bán, khả năng của sản phẩm...), hoặc khẳng định sai so với tài liệu.
Trả JSON: {"correct": true|false, "reason": "<ngắn gọn>"}"""


async def judge(item: dict, reply: str) -> tuple[bool, str, float]:
    in_scope = item["type"] != "out_of_scope"
    user = f"CÂU HỎI: {item['question']}\n"
    if in_scope:
        user += f"ĐÁP ÁN THAM CHIẾU: {item['reference']}\n"
        if item.get("expected_doc"):
            # Week 4: the judge sees the source document, so extra correct detail is not penalised
            # (it had marked r01/n04 wrong for adding true facts the short reference lacked).
            user += f"TÀI LIỆU GỐC:\n{doc_text(item['expected_doc'])}\n"
    else:
        # Without the KB the judge treated true facts (membership discounts) as fabrications.
        user += f"TÀI LIỆU CỬA HÀNG:\n{all_docs_text()}\n"
    user += f"CÂU TRẢ LỜI: {reply}"
    r = await llm.complete(
        [{"role": "system", "content": JUDGE_IN_SCOPE if in_scope else JUDGE_OUT_OF_SCOPE},
         {"role": "user", "content": user}],
        model=get_settings().llm_model_large,  # a stronger judge than the model under test
        json_mode=True,
        temperature=0,
        max_tokens=200,
    )
    data = json.loads(r.text)
    return bool(data.get("correct")), str(data.get("reason", "")), r.cost_usd


async def run_one(item: dict, mode: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        usage = Usage()
        started = time.perf_counter()
        context, cites, action, tools_used, extra = [], [], "none", [], {}
        if mode == "baseline":
            r = await llm.complete(
                [{"role": "system", "content": system_prompt("web")},
                 {"role": "user", "content": item["question"]}]
            )
            usage.add_result(r)
            reply = r.text
        else:
            ctx = AgentContext(session_id=f"eval_{item['id']}", channel="telegram", user_id="eval",
                               turn_id="t", dry_run=True, usage=usage)
            turn = await pipeline.handle(item["question"], ctx, [])
            out = turn.out
            reply, cites, action = out.answer, out.citations, out.action
            extra = {"grounding": out.grounding, "blocked_by": turn.blocked_by}
            context = list(ctx.retrieved.values())
            tools_used = [t["tool"] for t in ctx.tool_log]
        latency = time.perf_counter() - started
        if item["type"] == "action":
            # Actions are graded deterministically: did the agent call the right tool?
            correct = item["expected_tool"] in tools_used
            reason, judge_cost = f"tools called: {tools_used}", 0.0
        else:
            correct, reason, judge_cost = await judge(item, reply)

    row = {
        "id": item["id"], "type": item["type"], "question": item["question"], "answer": reply,
        "correct": correct, "reason": reason, "action": action, "tools": tools_used,
        "citations": [c.chunk_id for c in cites], "latency_s": round(latency, 2),
        "cost_usd": usage.cost_usd, "judge_cost_usd": judge_cost, **extra,
    }
    if mode == "agent" and "expected_tool" in item:
        row["tool_correct"] = item["expected_tool"] in tools_used
    if mode == "agent" and item.get("expected_doc"):
        row["context_rank"] = first_relevant_rank([c.hit for c in context], item)
        row["cites_expected_doc"] = any(c.doc_id == item["expected_doc"] for c in cites)
    return row


def summarize(rows: list[dict], mode: str) -> dict:
    def acc(t):
        sel = [r for r in rows if r["type"] == t]
        return sum(r["correct"] for r in sel) / len(sel) if sel else 0.0

    lat = sorted(r["latency_s"] for r in rows)
    s = {
        "mode": mode,
        "n": len(rows),
        "accuracy_in_scope": acc("in_scope"),
        "accuracy_no_accent": acc("no_accent"),
        "correct_refusal_out_of_scope": acc("out_of_scope"),
        "action_tool_accuracy": acc("action"),
        "latency_avg_s": statistics.mean(lat),
        "latency_p95_s": lat[min(len(lat) - 1, int(0.95 * len(lat)))],
        "cost_per_1k_usd": statistics.mean(r["cost_usd"] for r in rows) * 1000,
        "judge_cost_usd": sum(r["judge_cost_usd"] for r in rows),
    }
    answerable = [r for r in rows if "context_rank" in r]
    if mode == "agent":
        graded = [r for r in rows if "tool_correct" in r]
        s["tool_selection"] = sum(r["tool_correct"] for r in graded) / len(graded)
        s["context_recall"] = sum(r["context_rank"] is not None for r in answerable) / len(answerable)
        cited = [r for r in answerable if r["correct"]]
        s["citation_to_expected_doc"] = (
            sum(r["cites_expected_doc"] for r in cited) / len(cited) if cited else 0.0
        )
        # Every golden question is legitimate, so any block is a false positive of the guardrails.
        s["false_block_rate"] = sum(bool(r.get("blocked_by")) for r in rows) / len(rows)
        s["grounding"] = dict(Counter(r.get("grounding", "skipped") for r in rows))
    return s


def to_markdown(s: dict, rows: list[dict], settings) -> str:
    lines = [
        f"# Eval report — {s['mode']} — {dt.date.today().isoformat()}",
        "",
        f"Model `{settings.llm_model_small}`, judge `{settings.llm_model_large}`, {s['n']} questions."
        + (f" Chunking `{settings.chunk_strategy}`, rerank `{settings.rerank}`, top_k {settings.top_k}."
           if s["mode"] == "agent" else ""),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accuracy (in-scope) | {pct(s['accuracy_in_scope'])} |",
        f"| Accuracy (no-accent queries) | {pct(s['accuracy_no_accent'])} |",
        f"| Correct refusal (out-of-scope) | {pct(s['correct_refusal_out_of_scope'])} |",
    ]
    if s["mode"] == "agent":
        lines.append(f"| Actions: called the right tool | {pct(s['action_tool_accuracy'])} |")
    if s["mode"] == "agent":
        lines += [
            f"| Called the expected tool | {pct(s['tool_selection'])} |",
            f"| Context recall (relevant chunk in prompt) | {pct(s['context_recall'])} |",
            f"| Correct answers citing the expected doc | {pct(s['citation_to_expected_doc'])} |",
            f"| Legit questions blocked by guardrails | {pct(s['false_block_rate'])} |",
            f"| Grounding outcomes | {s['grounding']} |",
        ]
    lines += [
        f"| Latency avg / p95 | {s['latency_avg_s']:.2f}s / {s['latency_p95_s']:.2f}s |",
        f"| Cost per 1,000 questions | ${s['cost_per_1k_usd']:.3f} |",
        "",
        "## Failures",
        "",
        "| id | question | answer | judge |",
        "|---|---|---|---|",
    ]
    for r in rows:
        if not r["correct"]:
            ans = r["answer"].replace("\n", " ").replace("|", "/")[:160]
            lines.append(f"| {r['id']} | {r['question']} | {ans} | {r['reason']} |")
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "agent"], default="agent")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--tag", default="", help="suffix for the report file name")
    args = parser.parse_args()

    # Never read from or write into the production semantic cache during an eval.
    get_settings().semcache_collection = "semcache_eval"
    await semantic.clear()

    items = load_golden()
    sem = asyncio.Semaphore(args.concurrency)

    async def safe(item: dict) -> dict:
        # One network failure must not throw away the whole (paid) run; retry the item once.
        for attempt in (1, 2):
            try:
                return await run_one(item, args.mode, sem)
            except Exception as err:  # noqa: BLE001
                if attempt == 2:
                    raise RuntimeError(f"{item['id']} failed twice: {err!r}") from err
        raise AssertionError("unreachable")

    rows = await asyncio.gather(*(safe(i) for i in items))
    s = summarize(rows, args.mode)

    REPORTS.mkdir(exist_ok=True)
    stem = REPORTS / f"{dt.date.today().isoformat()}_{args.mode}{'_' + args.tag if args.tag else ''}"
    stem.with_suffix(".json").write_text(
        json.dumps({"summary": s, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stem.with_suffix(".md").write_text(to_markdown(s, rows, get_settings()), encoding="utf-8")
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
