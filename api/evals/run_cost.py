"""Cost/latency A/B on replayed FAQ traffic.

    python -m evals.run_cost --profile off   # semantic cache and router disabled
    python -m evals.run_cost --profile on    # production settings

Traffic = the 40 questions of cache_pairs.jsonl: every first question ("a") is asked first, then all the
second questions ("b"): 20 paraphrases (a cache hit is correct) and 20 near misses (a cache hit would be a
wrong answer). Every answer in the "on" profile is judged by gpt-4o against the full knowledge base, so a
cheaper but wrong answer cannot hide behind a lower bill. Writes evals/reports/<date>_cost_<profile>.md/json."""

import argparse
import asyncio
import datetime as dt
import json
import statistics
import time

from app.agent import pipeline
from app.agent.tools import AgentContext
from app.cache import semantic
from app.core.config import get_settings
from app.llm import client as llm
from app.llm.cost import Usage
from evals.common import HERE, REPORTS, all_docs_text, load_jsonl, pct

JUDGE = """Bạn là giám khảo. Dựa vào TÀI LIỆU CỬA HÀNG, câu trả lời có đúng cho CÂU HỎI không?
"correct" = true nếu thông tin trả lời đúng với tài liệu cho đúng điều được hỏi (đúng sản phẩm, hạng, khu vực, \
điều kiện), hoặc nói chưa có thông tin khi tài liệu không đề cập. false nếu sai hoặc trả lời cho một câu hỏi khác.
Trả JSON: {"correct": true|false, "reason": "<ngắn gọn>"}"""


async def judge(question: str, answer: str, docs: str) -> tuple[bool, str]:
    r = await llm.complete(
        [{"role": "system", "content": JUDGE},
         {"role": "user", "content": f"TÀI LIỆU CỬA HÀNG:\n{docs}\n\nCÂU HỎI: {question}\nCÂU TRẢ LỜI: {answer}"}],
        model=get_settings().llm_model_large, json_mode=True, temperature=0, max_tokens=150,
    )
    data = json.loads(r.text)
    return bool(data.get("correct")), str(data.get("reason", ""))


async def turn(i: int, q: str, kind: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        usage = Usage()
        ctx = AgentContext(session_id=f"cost_{i}", channel="telegram", user_id=f"cost_{i}", turn_id="t",
                           dry_run=True, usage=usage)
        started = time.perf_counter()
        res = await pipeline.handle(q, ctx, [])
        return {"i": i, "kind": kind, "question": q, "answer": res.out.answer, "route": res.route,
                "latency_s": time.perf_counter() - started, "cost_usd": usage.cost_usd,
                "tokens_in": usage.tokens_in, "cached_tokens": usage.cached_tokens, "llm_calls": usage.llm_calls}


def pctl(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["on", "off"], default="on")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    s = get_settings()
    s.semantic_cache = s.router_enabled = args.profile == "on"
    s.semcache_collection = "semcache_eval"
    await semantic.clear()

    pairs = load_jsonl(HERE / "cache_pairs.jsonl")
    firsts = list(dict.fromkeys(p["a"] for p in pairs))  # unique, in order
    seconds = [(p["b"], "paraphrase" if p["same"] else "near_miss") for p in pairs]

    sem = asyncio.Semaphore(args.concurrency)
    rows = list(await asyncio.gather(*(turn(i, q, "first", sem) for i, q in enumerate(firsts))))
    n = len(rows)
    rows += await asyncio.gather(*(turn(n + i, q, k, sem) for i, (q, k) in enumerate(seconds)))
    await semantic.clear()

    if args.profile == "on":
        docs = all_docs_text()
        verdicts = await asyncio.gather(*(judge(r["question"], r["answer"], docs) for r in rows))
        for r, (ok, why) in zip(rows, verdicts, strict=True):
            r["correct"], r["judge"] = ok, why

    lat = [r["latency_s"] for r in rows]
    cost = sum(r["cost_usd"] for r in rows)
    summary = {
        "profile": args.profile,
        "turns": len(rows),
        "cost_per_1k_turns_usd": cost / len(rows) * 1000,
        "latency_avg_s": statistics.mean(lat), "latency_p50_s": pctl(lat, 0.5), "latency_p95_s": pctl(lat, 0.95),
        "routes": {k: sum(r["route"] == k for r in rows) for k in ("small", "large", "cache", "blocked")},
        "cache_hits_on_paraphrases": sum(r["route"] == "cache" for r in rows if r["kind"] == "paraphrase"),
        "cache_hits_on_near_misses": sum(r["route"] == "cache" for r in rows if r["kind"] == "near_miss"),
        "prompt_cached_share": sum(r["cached_tokens"] for r in rows) / max(1, sum(r["tokens_in"] for r in rows)),
        "llm_calls_per_turn": statistics.mean(r["llm_calls"] for r in rows),
    }
    if args.profile == "on":
        summary["accuracy"] = sum(r["correct"] for r in rows) / len(rows)
        summary["accuracy_cache_hits"] = (
            sum(r["correct"] for r in rows if r["route"] == "cache")
            / max(1, sum(r["route"] == "cache" for r in rows)))

    stem = REPORTS / f"{dt.date.today().isoformat()}_cost_{args.profile}"
    REPORTS.mkdir(exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False,
                                                    indent=2), encoding="utf-8")
    lines = [f"# Cost replay — {args.profile} — {dt.date.today().isoformat()}", "",
             "| Metric | Value |", "|---|---|",
             *[f"| {k} | {pct(v) if 'share' in k or 'accuracy' in k else v} |" for k, v in summary.items()], "",
             "## Turns", "", "| kind | route | correct | question | answer |", "|---|---|---|---|---|",
             *[f"| {r['kind']} | {r['route']} | {r.get('correct', '')} | {r['question']} | "
               f"{r['answer'][:90].replace(chr(10), ' ')} |" for r in rows]]
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
