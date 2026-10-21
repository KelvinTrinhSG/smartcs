-- Week 5: richer usage logs for cost reporting (WF-30) and budget alerts (WF-31).
-- Existing DB: docker compose exec -T postgres psql -U smartcs -d smartcs < data/seed/03_cost.sql
ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS route TEXT NOT NULL DEFAULT 'small';  -- small|large|cache|blocked|rate_limited
ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS cached_tokens INT NOT NULL DEFAULT 0;   -- OpenAI prompt-cache tokens
ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS llm_calls INT NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS usage_logs_created_idx ON usage_logs (created_at);
