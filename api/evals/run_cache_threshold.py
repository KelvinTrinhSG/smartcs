"""Pick the semantic-cache similarity threshold from data.

    python -m evals.run_cache_threshold

cache_pairs.jsonl holds paraphrase pairs (same answer: should hit) and near misses that differ only in the
product, tier, region or payment method (different answer: must NOT hit). A false hit serves a wrong answer,
so the threshold is the lowest one with zero false hits, and the report shows how much recall that leaves."""

import asyncio
import datetime as dt
import math

from app.cache import semantic
from app.llm import client as llm
from evals.common import HERE, REPORTS, load_jsonl, pct


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def main() -> None:
    pairs = load_jsonl(HERE / "cache_pairs.jsonl")
    texts = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
    vecs = dict(zip(texts, await llm.embed(texts), strict=True))
    for p in pairs:
        p["sim"] = cosine(vecs[p["a"]], vecs[p["b"]])

    same = sorted(p["sim"] for p in pairs if p["same"])
    diff = sorted(p["sim"] for p in pairs if not p["same"])
    safe = max(diff) + 0.005  # lowest threshold with no false hit on this set (small margin)

    rows = []
    for t in [0.80, 0.85, 0.88, 0.90, 0.92, 0.94, 0.96, round(safe, 3)]:
        hits_same = sum(s >= t for s in same)
        hits_diff = sum(s >= t for s in diff)
        rows.append((t, hits_same / len(same), hits_diff))

    # Vector candidate + LLM verifier (what production uses).
    verdicts = await asyncio.gather(*(semantic.same_answer(p["a"], p["b"]) for p in pairs))
    for p, v in zip(pairs, verdicts, strict=True):
        p["verified"] = v
    vrows = []
    for t in [0.50, 0.60, 0.65, 0.70, 0.75, 0.80]:
        hit = [p for p in pairs if p["sim"] >= t and p["verified"]]
        vrows.append((t, sum(p["same"] for p in hit) / len(same), sum(not p["same"] for p in hit)))
    verifier_errors = [p for p in pairs if p["verified"] != p["same"]]

    lines = [
        f"# Semantic cache threshold — {dt.date.today().isoformat()}", "",
        f"{len(same)} paraphrase pairs (should hit), {len(diff)} near-miss pairs (must not hit), "
        "`text-embedding-3-small`, cosine similarity.", "",
        f"- Paraphrases: min {same[0]:.3f}, median {same[len(same) // 2]:.3f}, max {same[-1]:.3f}",
        f"- Near misses: min {diff[0]:.3f}, median {diff[len(diff) // 2]:.3f}, **max {diff[-1]:.3f}**",
        "", "## Cosine threshold only", "",
        "| Threshold | Paraphrase recall | False hits (wrong answer served) |", "|---|---|---|",
        *[f"| {t:.3f} | {pct(r)} | {fh} |" for t, r, fh in rows], "",
        "## Cosine candidate + gpt-4o-mini verifier (production)", "",
        "| Candidate threshold | Paraphrase recall | False hits |", "|---|---|---|",
        *[f"| {t:.2f} | {pct(r)} | {fh} |" for t, r, fh in vrows], "",
        f"Verifier disagreements with the label: {len(verifier_errors)}/{len(pairs)}", "",
        *[f"- ({'same' if p['same'] else 'different'}) {p['a']} / {p['b']}" for p in verifier_errors], "",
        "## Closest near misses", "", "| similarity | a | b |", "|---|---|---|",
        *[f"| {p['sim']:.3f} | {p['a']} | {p['b']} |"
          for p in sorted((p for p in pairs if not p["same"]), key=lambda p: -p["sim"])[:6]],
        "", "## Paraphrases below the safe threshold", "", "| similarity | a | b |", "|---|---|---|",
        *[f"| {p['sim']:.3f} | {p['a']} | {p['b']} |"
          for p in sorted((p for p in pairs if p["same"] and p["sim"] < safe), key=lambda p: -p["sim"])],
    ]
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{dt.date.today().isoformat()}_cache_threshold.md").write_text("\n".join(lines) + "\n",
                                                                               encoding="utf-8")
    print("\n".join(lines[:12]))
    for t, r, fh in rows:
        print(f"cosine only     t={t:.3f} recall={pct(r)} false_hits={fh}")
    for t, r, fh in vrows:
        print(f"cosine+verifier t={t:.2f} recall={pct(r)} false_hits={fh}")
    print(f"verifier errors: {[(p['a'][:30], p['b'][:30], p['same']) for p in verifier_errors]}")


if __name__ == "__main__":
    asyncio.run(main())
