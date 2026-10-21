# SmartCS — AI customer service assistant (n8n + Python)

Multi-channel AI support assistant for a mock electronics shop, **TechZone**.

- **Python (FastAPI)** is the "brain": agent loop, RAG, guardrails, model routing, cost tracking, evals.
- **n8n** handles the plumbing: Telegram/web channels, voice (STT/TTS), business tools (tickets, email, calendar, handoff), scheduled reports.

> Status: **Week 2 — RAG.** Answers are grounded in the knowledge base with validated citations.
> Agent tools, guardrails and voice land in later weeks.

## Architecture

```
Telegram / Web ──► n8n (WF-01, WF-02) ──X-Internal-Key──► FastAPI /v1/chat
                                                              │
                     ┌────────────────────────────────────────┘
                     ▼
     embed query ─► hybrid search (Qdrant dense + BM25 sparse, RRF) ─► LLM rerank ─► threshold
                     ─► grounded answer (JSON) ─► citation check ─► answer + citations + action
```

## Results (Week 2)

Golden set: 55 Vietnamese questions (41 in-scope, 5 typed without diacritics, 8 out-of-scope),
model `gpt-4o-mini`, judged by `gpt-4o-mini`. Full reports in [api/evals/reports/](api/evals/reports/).

| Metric | Baseline (no RAG) | RAG |
|---|---|---|
| Accuracy, in-scope | 7.1% | **100%** |
| Accuracy, no-diacritics queries | 20.0% | **100%** |
| Correct refusal, out-of-scope | 87.5% | **100%** |
| Relevant chunk in prompt (context recall) | — | 100% |
| Correct answers citing the expected doc | — | 100% |
| Latency avg / p95 | 1.49s / 2.91s | 3.28s / 5.81s |
| Cost per 1,000 questions | $0.05 | $0.28 |

Example: *"Laptop ASUS Vivobook bảo hành bao lâu?"* — baseline guessed **12 months**; RAG answers
**24 months** citing `policy_warranty#0`.

Retrieval-only comparison of chunking × search mode (47 answerable questions, no rerank):

| Chunking | Dense MRR | Sparse MRR | **Hybrid MRR** | Hybrid Hit@1 |
|---|---|---|---|---|
| fixed (400 chars, 80 overlap) | 0.805 | 0.790 | 0.907 | 83.0% |
| recursive (≤600 chars) | 0.815 | 0.877 | 0.933 | 87.2% |
| section (markdown headings) | 0.878 | 0.859 | 0.919 | 85.1% |

**Takeaways**
- Hybrid beats dense-only and sparse-only for every chunking strategy; RRF needs no score calibration.
- Sparse vectors index syllable bigrams and a diacritics-stripped copy, so "bao hanh" matches "bảo hành".
- `recursive` vs `section` differ by one question (within noise). `section` is the default because its
  heading path gives readable citations.

**Caveats (honest reading of the 100%)**
- The KB is small (6 docs, 25 chunks) and questions were written by the same author as the docs; real
  user phrasing will be messier. Next step: collect real questions from the Telegram logs.
- The judge is the same small model and is lenient: it scored a baseline answer that asserted
  "TechZone only sells electronics" as a correct refusal. Plan: stronger judge + hand-checked sample.
- RAG costs ~5× more and doubles latency (embedding + rerank call + longer prompt). Week 5 targets this
  with routing, semantic cache and skipping rerank when the top hit is already confident.

## Quick start

```bash
cp .env.example .env        # fill in OPENAI_API_KEY and the secrets
docker compose up -d --build
curl http://localhost:8000/healthz

# load the knowledge base into Qdrant
docker compose exec api python -m app.rag.cli ingest /data/docs
```

Or ingest one document over HTTP (used by WF-20 later):

```bash
curl -X POST http://localhost:8000/v1/ingest -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"policy_x","content":"# Title\n\n## Section\nText...","mime_type":"text/markdown"}'
```

Run evals (inside the api container):

```bash
docker compose exec api python -m evals.compare_chunking --docs /data/docs
docker compose exec api python -m evals.run_eval --mode baseline
docker compose exec api python -m evals.run_eval --mode rag
```

Call the API directly:

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -d '{"session_id":"s1","channel":"web","user":{"id":"u1"},"message":"Chính sách bảo hành laptop?"}'
```

Import n8n workflows and call the web chat entry:

```bash
docker compose exec n8n n8n import:workflow --separate --input=/workflows
# then open http://localhost:5679 (host port 5679, so a local n8n on 5678 can coexist)
# and activate "WF-02 Web Chat Entry"
curl -X POST http://localhost:5679/webhook/chat/web \
  -H "Content-Type: application/json" -d '{"session_id":"abc","message":"Xin chào"}'
```

### Telegram (WF-01)

Telegram needs a public HTTPS webhook. In dev, a Cloudflare Quick Tunnel runs behind a small Caddy
gateway ([deploy/Caddyfile.dev](deploy/Caddyfile.dev)) that only exposes `/webhook/*`, never the n8n editor.

1. Create a bot with [@BotFather](https://t.me/BotFather) and set `TELEGRAM_BOT_TOKEN` in `.env`.
2. In n8n, create a *Telegram API* credential named `TechZone SmartCS Bot`, then import and activate WF-01.
3. Start the tunnel and register the webhook (re-run whenever the tunnel restarts, the URL changes):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\tunnel_url.ps1
```

If an antivirus/proxy inspects HTTPS (e.g. Kaspersky), put its root CA at `certs/extra-ca.pem`.

## Tests

```bash
cd api
pip install -r requirements-dev.txt
pytest -q
```

## Repository layout

```
api/app/rag/      chunking, sparse vectors, Qdrant store, hybrid retriever, rerank, citations
api/evals/        golden set, eval runners, reports
n8n/workflows/    exported n8n workflows (no credentials)
data/docs/        mock policy documents (knowledge base)
data/seed/        SQL schema + mock products/orders
.github/workflows CI: ruff, pytest, workflow validation, gitleaks
```

## Roadmap

- [x] Week 1 — docker-compose, `/v1/chat`, web chat entry, mock data
- [x] Week 1 — Telegram entry (WF-01)
- [x] Week 2 — RAG: ingest, chunking, hybrid search, rerank, golden set baseline
- [ ] Week 2 — WF-20 Google Drive → `/v1/ingest` sync (needs Google credential in n8n)
- [ ] Week 3 — agent loop + n8n tools (ticket, appointment, handoff)
- [ ] Week 4 — hallucination control & security (PII, injection, grounding)
- [ ] Week 5 — voice, routing, semantic cache, cost reports
- [ ] Week 6 — CI/CD, deploy, demo
