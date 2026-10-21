# SmartCS — AI customer service assistant (n8n + Python)

Multi-channel AI support assistant for a mock electronics shop, **TechZone**.

- **Python (FastAPI)** is the "brain": agent loop, RAG, guardrails, model routing, cost tracking, evals.
- **n8n** handles the plumbing: Telegram/web channels, voice (STT/TTS), business tools (tickets, email, calendar, handoff), scheduled reports.

> Status: **Week 1 — skeleton.** `/v1/chat` is a plain LLM call; RAG, tools and guardrails land in later weeks.

## Architecture

```
Telegram / Web ──► n8n (WF-01, WF-02) ──X-Internal-Key──► FastAPI /v1/chat ──► LLM (LiteLLM)
                                                              │
                                     Postgres · Redis · Qdrant ┘
```

## Quick start

```bash
cp .env.example .env        # fill in OPENAI_API_KEY and the secrets
docker compose up -d --build
curl http://localhost:8000/healthz
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
api/              FastAPI service
n8n/workflows/    exported n8n workflows (no credentials)
data/docs/        mock policy documents (knowledge base)
data/seed/        SQL schema + mock products/orders
.github/workflows CI: ruff, pytest, workflow validation, gitleaks
```

## Roadmap

- [x] Week 1 — docker-compose, `/v1/chat`, web chat entry, mock data
- [x] Week 1 — Telegram entry (WF-01)
- [ ] Week 2 — RAG: ingest, chunking, hybrid search, rerank, golden set baseline
- [ ] Week 3 — agent loop + n8n tools (ticket, appointment, handoff)
- [ ] Week 4 — hallucination control & security (PII, injection, grounding)
- [ ] Week 5 — voice, routing, semantic cache, cost reports
- [ ] Week 6 — CI/CD, deploy, demo
