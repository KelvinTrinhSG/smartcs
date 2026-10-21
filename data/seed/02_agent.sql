-- Week 3: agent memory, identity and the records written by n8n tool workflows.
-- Runs automatically on a fresh volume; for an existing DB apply with:
--   docker compose exec -T postgres psql -U smartcs -d smartcs < data/seed/02_agent.sql

-- Phone numbers verified through Telegram "share contact" (contact.user_id == from.id).
CREATE TABLE IF NOT EXISTS verified_users (
    user_id     TEXT PRIMARY KEY,
    phone       TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Conversation history (user/assistant text only; tool traces are not stored).
CREATE TABLE IF NOT EXISTS messages (
    id         BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_session_idx ON messages (session_id, id DESC);

-- Written by n8n WF-10. idempotency_key makes retries safe.
CREATE SEQUENCE IF NOT EXISTS ticket_seq START 1001;
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id       TEXT PRIMARY KEY DEFAULT ('TK' || nextval('ticket_seq')),
    idempotency_key TEXT UNIQUE NOT NULL,
    session_id      TEXT NOT NULL,
    customer_phone  TEXT,
    order_id        TEXT,
    category        TEXT NOT NULL,
    summary         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Written by n8n WF-11. One technician per store: a slot can be booked once.
CREATE SEQUENCE IF NOT EXISTS appointment_seq START 501;
CREATE TABLE IF NOT EXISTS appointments (
    event_id        TEXT PRIMARY KEY DEFAULT ('AP' || nextval('appointment_seq')),
    idempotency_key TEXT UNIQUE NOT NULL,
    session_id      TEXT NOT NULL,
    customer_phone  TEXT,
    store_id        TEXT NOT NULL,
    start_at        TIMESTAMPTZ NOT NULL,
    purpose         TEXT,
    status          TEXT NOT NULL DEFAULT 'booked',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, start_at)
);

-- Written by n8n WF-12.
CREATE TABLE IF NOT EXISTS handoffs (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    session_id      TEXT NOT NULL,
    reason          TEXT NOT NULL,
    summary         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
