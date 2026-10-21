#!/bin/sh
# Render start: build credentials from env, import credentials + workflows, publish them, start n8n.
set -e

# Render exposes the public URL at runtime; n8n registers the Telegram webhook with it.
export WEBHOOK_URL="${WEBHOOK_URL:-$RENDER_EXTERNAL_URL/}"
export N8N_EDITOR_BASE_URL="${N8N_EDITOR_BASE_URL:-$RENDER_EXTERNAL_URL/}"
# Shared with the API through a Render env group, where it is called INTERNAL_API_KEY.
export SMARTCS_INTERNAL_KEY="${SMARTCS_INTERNAL_KEY:-$INTERNAL_API_KEY}"
# Render's private-network reference is "host:port" without a scheme.
case "$SMARTCS_API_URL" in *://*) ;; *) export SMARTCS_API_URL="http://$SMARTCS_API_URL" ;; esac

CREDS=/tmp/credentials.json
node -e '
const e = process.env;
const creds = [
  { id: "tgcredsmartcs01", name: "TechZone SmartCS Bot", type: "telegramApi",
    data: { accessToken: e.TELEGRAM_BOT_TOKEN } },
  { id: "oaicredsmartcs01", name: "OpenAI SmartCS", type: "openAiApi",
    data: { apiKey: e.OPENAI_API_KEY, url: "https://api.openai.com/v1", header: false } },
  { id: "hdrinternal01", name: "SmartCS Internal Key", type: "httpHeaderAuth",
    data: { name: "X-Internal-Key", value: e.SMARTCS_INTERNAL_KEY } },
  { id: "pgsmartcs01", name: "SmartCS DB", type: "postgres",
    data: { host: e.APP_DB_HOST, port: Number(e.APP_DB_PORT || 5432), database: e.APP_DB_NAME,
            user: e.APP_DB_USER, password: e.APP_DB_PASSWORD, ssl: "disable" } },
];
for (const c of creds)
  for (const [k, v] of Object.entries(c.data))
    if (v === undefined || v === "") { console.error(`missing env for ${c.id}.${k}`); process.exit(1); }
require("fs").writeFileSync(process.argv[1], JSON.stringify(creds), { mode: 0o600 });
' "$CREDS"
n8n import:credentials --input="$CREDS"
rm -f "$CREDS"

n8n import:workflow --separate --input=/workflows
for f in /workflows/*.json; do
  id=$(node -p 'require(process.argv[1]).id' "$f")
  n8n publish:workflow --id="$id"
done

exec n8n start
