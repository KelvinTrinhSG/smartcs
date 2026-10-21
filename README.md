# SmartCS — AI customer service assistant (n8n + Python)

Multi-channel AI support assistant for a mock electronics shop, **TechZone**.

- **Python (FastAPI)** is the "brain": agent loop, RAG, guardrails, model routing, cost tracking, evals.
- **n8n** handles the plumbing: Telegram/web channels, voice (STT/TTS), business tools (tickets, email, calendar, handoff), scheduled reports.

> Status: **Week 3 — tool-using agent.** Grounded answers with citations, order lookup for verified
> customers, and tickets / appointments / human handoff executed by n8n. Guardrails and voice come next.

## Architecture

```
Telegram / Web ──► n8n WF-01/02 ──X-Internal-Key──► FastAPI /v1/chat
                                                       │  load verified phone + last 10 messages (Postgres)
                                                       ▼
     prefetch: search_kb on the customer's own words (+ lookup_order if it is about an order)
                                                       ▼
                    agent loop (gpt-4o-mini, max 5 steps, JSON final answer, citation check)
          ┌────────────┬───────────────┬───────────────────┬────────────────────┬───────────────────┐
     search_kb    lookup_order     create_ticket      book_appointment     handoff_to_human
     (Qdrant)     (Postgres,       └──────── POST n8n /webhook/tool/* (header auth, timeout,
                  own orders only)           2 retries, idempotency_key) ─► WF-10/11/12:
                                             Postgres insert ─► respond ─► notify staff on Telegram
```

| Tool | Runs in | Guard rails |
|---|---|---|
| `search_kb` | Python → Qdrant | Prefetched with the raw question; model may search again |
| `lookup_order` | Python → Postgres | Phone comes from the server (Telegram *share contact*, `contact.user_id == from.id`), never from the LLM; unknown and foreign orders look identical |
| `create_ticket` | n8n WF-10 | Pydantic-validated args; `order_id` must belong to the caller; idempotent |
| `book_appointment` | n8n WF-11 | ≥1h ahead, ≤30 days, 08:00–21:00 on :00/:30; one booking per store slot (DB unique) |
| `handoff_to_human` | n8n WF-12 | Staff gets a summary on Telegram and replies with `/reply <chat_id> <text>` |

Internal tool webhooks are not reachable through the public tunnel (`/webhook/tool/*` → 404).

## Results (Week 3: agent)

Golden set now has 59 questions: 42 in-scope, 5 without diacritics, 7 out-of-scope and 5 **actions**
(graded deterministically: was the right tool called?). Answers by `gpt-4o-mini`, judged by `gpt-4o`.

| Metric | Baseline (no RAG, no tools) | Agent |
|---|---|---|
| Accuracy, in-scope | 4.8% | **100%** |
| Accuracy, no-diacritics queries | 0% | **100%** |
| Correct refusal, out-of-scope | 42.9% | **85.7%** (6/7) |
| Actions: called the right tool | 0% | **100%** |
| Relevant chunk in context / correct answers citing expected doc | — | 100% / 100% |
| Latency avg / p95 | 1.30s / 2.27s | 3.54s / 4.89s |
| Cost per 1,000 questions | $0.05 | $0.38 |

**The eval caught a regression.** The first agent version (model writes its own `search_kb` query)
scored worse than the Week 2 RAG pipeline: in-scope 92.9%, no-diacritics **40%**, out-of-scope 75%.
Root causes and fixes:

| Failure | Cause | Fix |
|---|---|---|
| "Giao hàng ra Hải Phòng mất mấy ngày?" → "no information" | The model paraphrased the query and lost the "các tỉnh khác" chunk | Prefetch the KB with the customer's own words; also saves one LLM round trip (p95 8.3s → 4.7s) |
| Opening hours answered as 08:00–21:00 (actual 21:30) | The booking-slot hours in the tool prompt leaked into answers | Keep business facts out of prompts; the tool validates slots |
| "Create a warranty ticket" → "please call the hotline" | The KB says "contact SmartCS or the hotline"; the model did not know it *is* SmartCS | Prompt states the agent is that channel and must call `create_ticket` |
| Asserted "no trade-in programme" | No rule against claims absent from tool results | "Only answer from tool results; never assert what the docs don't say" |

A live multi-turn test then found two more issues that the single-turn eval could not see: the agent asked
an already-verified customer for their phone, and it refused "10h sáng mai" without calling the booking tool
(fix: give tomorrow's date, never pre-judge slots).

**…and caught the fix's own regression.** Telling the model "customer is *not* verified" made it answer order
and ticket requests itself ("please tap the share-phone button") without calling a tool: actions fell from
100% to **40%**, and in production the button would never have appeared because it is driven by
`action=request_phone`. Prompt wording alone only got back to 60%. The durable fix is deterministic: only the
*verified* state is announced, and when a message is clearly about an order (`đơn hàng`, `mã đơn`, `TZ…`)
the loop calls `lookup_order` itself before the first LLM turn, the same way it prefetches the KB.
Live check, unverified user: 5/6 order questions now show the button; the miss ("Laptop tôi mua tháng 7 còn
bảo hành không?") never mentions an order and is answered from the warranty policy instead.

**Eval changes, disclosed:** judge upgraded from `gpt-4o-mini` to `gpt-4o` (the small judge marked correct
answers wrong and a fabricated refusal right); `o03` (order status) moved from out-of-scope to action now that
`lookup_order` exists; `n01`'s reference answer clarified. Baseline was re-run on the same set and judge.

**Remaining failure:** `o08` — asked whether a MacBook Air M3 can run Windows, the model answers from its own
knowledge and stitches in the (unrelated) Windows reinstall fee. This is what the Week 4 grounding check is for.
Judge variance is visible too: `r01` (a correct answer with extra correct detail) failed in some runs.

**Found in production-like testing:** the first call to a tool webhook sometimes took >10s because n8n sent
the staff Telegram notification *before* responding. The API timed out and retried; the idempotency key made
the retry return the same ticket instead of a duplicate. Workflows now respond first and notify afterwards
(tool latency 20s → 0.2–0.6s).

## Results (Week 2: RAG)

Golden set at the time: 55 Vietnamese questions (41 in-scope, 5 typed without diacritics, 8 out-of-scope),
model `gpt-4o-mini`, judged by `gpt-4o-mini` (a weaker judge than Week 3, so numbers are not directly
comparable). Full reports in [api/evals/reports/](api/evals/reports/).

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
docker compose exec api python -m evals.run_eval --mode agent   # side-effect tools run dry
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

### Agent tools (WF-10/11/12)

1. Apply the agent schema to an existing database (fresh volumes get it automatically):
   `docker compose exec -T postgres psql -U smartcs -d smartcs < data/seed/02_agent.sql`
2. In n8n create two credentials: *Postgres* `SmartCS DB` (host `postgres`, db `smartcs`) and
   *Header Auth* `SmartCS Internal Key` (name `X-Internal-Key`, value = `INTERNAL_API_KEY`).
3. Set `STAFF_TELEGRAM_CHAT_ID` in `.env` (the chat that receives tickets, bookings and handoffs).
4. Import and activate WF-10, WF-11, WF-12 and the updated WF-01.

On Telegram, order questions show a **📱 Chia sẻ số điện thoại** button; sharing your own contact verifies the
phone. Staff answer escalations with `/reply <chat_id> <message>` from the staff chat.

## Tests

```bash
cd api
pip install -r requirements-dev.txt
pytest -q
```

## Repository layout

```
api/app/agent/    agent loop, tools (Pydantic-validated), n8n client, prompts
api/app/db/       Postgres access (verified phones, orders, history, usage)
api/app/rag/      chunking, sparse vectors, Qdrant store, hybrid retriever, rerank, citations
api/tests/        unit tests + integration tests with n8n mocked via respx
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
- [x] Week 3 — agent loop + n8n tools (ticket, appointment, handoff), phone verification, memory
- [ ] Week 3 — Google Sheets / Gmail / Calendar in WF-10/11 (records currently live in Postgres)
- [ ] Week 4 — hallucination control & security (PII, injection, grounding)
- [ ] Week 5 — voice, routing, semantic cache, cost reports
- [ ] Week 6 — CI/CD, deploy, demo
