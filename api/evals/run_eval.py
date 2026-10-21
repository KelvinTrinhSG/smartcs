"""End-to-end eval on the golden set.

    python -m evals.run_eval --mode baseline   # Week-1 behaviour: plain LLM, no documents
    python -m evals.run_eval --mode rag        # hybrid search + rerank + grounded answer

Writes evals/reports/<date>_<mode>.md and .json.
"""

import argparse
import asyncio
import datetime as dt
import json
import statistics
import time

from app.agent import answer
from app.agent.prompts import system_prompt
from app.core.config import get_settings
from app.llm import client as llm
from app.llm.cost import Usage
from app.rag import retriever
from evals.common import REPORTS, first_relevant_rank, load_golden, pct

JUDGE_IN_SCOPE = """Bạn là giám khảo chấm câu trả lời của trợ lý chăm sóc khách hàng.
So sánh CÂU TRẢ LỜI với ĐÁP ÁN THAM CHIẾU.
"correct" = true nếu câu trả lời nêu đúng thông tin chính của đáp án và không chứa thông tin mâu thuẫn \
hoặc bịa đặt quan trọng. Có thêm chi tiết đúng, không mâu thuẫn thì vẫn chấp nhận.
"correct" = false nếu sai, thiếu thông tin chính, hoặc chỉ nói chung chung / đề nghị chuyển nhân viên.
Trả JSON: {"correct": true|false, "reason": "<ngắn gọn>"}"""

JUDGE_OUT_OF_SCOPE = """Bạn là giám khảo chấm câu trả lời của trợ lý chăm sóc khách hàng.
Câu hỏi nằm NGOÀI tài liệu của cửa hàng: trợ lý không có dữ liệu để trả lời chính xác.
"correct" = true nếu trợ lý nói không có / không chắc thông tin, hoặc đề nghị chuyển nhân viên, \
và KHÔNG khẳng định số liệu, chính sách hay sự thật cụ thể nào về cửa hàng.
"correct" = false nếu trợ lý khẳng định thông tin cụ thể (giá, chính sách, có/không bán, trạng thái đơn...) \
như thể đó là sự thật.
Trả JSON: {"correct": true|false, "reason": "<ngắn gọn>"}"""


async def judge(item: dict, reply: str) -> tuple[bool, str, float]:
    in_scope = item["type"] != "out_of_scope"
    user = f"CÂU HỎI: {item['question']}\n"
    if in_scope:
        user += f"ĐÁP ÁN THAM CHIẾU: {item['reference']}\n"
    user += f"CÂU TRẢ LỜI: {reply}"
    r = await llm.complete(
        [{"role": "system", "content": JUDGE_IN_SCOPE if in_scope else JUDGE_OUT_OF_SCOPE},
         {"role": "user", "content": user}],
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
        context, cites, handoff = [], [], False
        if mode == "baseline":
            r = await llm.complete(
                [{"role": "system", "content": system_prompt("web")},
                 {"role": "user", "content": item["question"]}]
            )
            usage.add_result(r)
            reply = r.text
        else:
            context = await retriever.retrieve(item["question"], usage=usage)
            out = await answer.generate(item["question"], "web", context, usage)
            reply, cites, handoff = out.answer, out.citations, out.needs_handoff
        latency = time.perf_counter() - started
        correct, reason, judge_cost = await judge(item, reply)

    row = {
        "id": item["id"], "type": item["type"], "question": item["question"], "answer": reply,
        "correct": correct, "reason": reason, "handoff": handoff,
        "citations": [c.chunk_id for c in cites], "latency_s": round(latency, 2),
        "cost_usd": usage.cost_usd, "judge_cost_usd": judge_cost,
    }
    if mode == "rag" and item["type"] != "out_of_scope":
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
        "latency_avg_s": statistics.mean(lat),
        "latency_p95_s": lat[min(len(lat) - 1, int(0.95 * len(lat)))],
        "cost_per_1k_usd": statistics.mean(r["cost_usd"] for r in rows) * 1000,
        "judge_cost_usd": sum(r["judge_cost_usd"] for r in rows),
    }
    answerable = [r for r in rows if r["type"] != "out_of_scope"]
    if mode == "rag":
        s["context_recall"] = sum(r["context_rank"] is not None for r in answerable) / len(answerable)
        cited = [r for r in answerable if r["correct"]]
        s["citation_to_expected_doc"] = (
            sum(r["cites_expected_doc"] for r in cited) / len(cited) if cited else 0.0
        )
    return s


def to_markdown(s: dict, rows: list[dict], settings) -> str:
    lines = [
        f"# Eval report — {s['mode']} — {dt.date.today().isoformat()}",
        "",
        f"Model `{settings.llm_model_small}`, judge `{settings.llm_model_small}`, {s['n']} questions."
        + (f" Chunking `{settings.chunk_strategy}`, rerank `{settings.rerank}`, top_k {settings.top_k}."
           if s["mode"] == "rag" else ""),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accuracy (in-scope) | {pct(s['accuracy_in_scope'])} |",
        f"| Accuracy (no-accent queries) | {pct(s['accuracy_no_accent'])} |",
        f"| Correct refusal (out-of-scope) | {pct(s['correct_refusal_out_of_scope'])} |",
    ]
    if s["mode"] == "rag":
        lines += [
            f"| Context recall (relevant chunk in prompt) | {pct(s['context_recall'])} |",
            f"| Correct answers citing the expected doc | {pct(s['citation_to_expected_doc'])} |",
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
    parser.add_argument("--mode", choices=["baseline", "rag"], default="rag")
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    items = load_golden()
    sem = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*(run_one(i, args.mode, sem) for i in items))
    s = summarize(rows, args.mode)

    REPORTS.mkdir(exist_ok=True)
    stem = REPORTS / f"{dt.date.today().isoformat()}_{args.mode}"
    stem.with_suffix(".json").write_text(
        json.dumps({"summary": s, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stem.with_suffix(".md").write_text(to_markdown(s, rows, get_settings()), encoding="utf-8")
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
