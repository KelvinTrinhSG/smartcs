"""PII masking eval (no LLM calls): recall on labelled samples, false positives on the golden questions
and every knowledge-base document.  python -m evals.run_pii"""

from collections import Counter

from app.guardrails import pii
from evals.common import DOCS_DIR, HERE, load_golden, load_jsonl, pct


def main() -> None:
    samples = load_jsonl(HERE / "pii_set.jsonl")
    expected_total, caught, extra, misses = 0, 0, 0, []
    for s in samples:
        found = pii.mask(s["text"]).found
        expect = Counter(s["expect"])
        expected_total += sum(expect.values())
        caught += sum(min(found[k], v) for k, v in expect.items())
        extra += sum((found - expect).values())
        if found != expect:
            misses.append((s["text"], dict(expect), dict(found)))

    golden_fp = [i["question"] for i in load_golden() if pii.mask(i["question"]).changed]
    doc_fp = {p.name: dict(pii.mask(p.read_text(encoding="utf-8")).found)
              for p in sorted(DOCS_DIR.glob("*.md")) if pii.mask(p.read_text(encoding="utf-8")).changed}

    print(f"Recall on labelled PII: {caught}/{expected_total} = {pct(caught / expected_total)}")
    print(f"Spurious masks on labelled samples: {extra}")
    print(f"False positives on golden questions: {len(golden_fp)}")
    print(f"False positives in KB documents: {doc_fp or 'none'}")
    for text, exp, got in misses:
        print(f"  MISMATCH {text!r}: expected {exp}, got {got}")


if __name__ == "__main__":
    main()
