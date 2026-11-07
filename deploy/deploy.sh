#!/usr/bin/env bash
# Release the version checked out at /srv/caresense/app. Run on the server:
#
#   cd /srv/caresense/app && sudo -u caresense git pull && sudo bash deploy/deploy.sh
#
# One-time server setup comes first: Backend/docs/operations.md, "Deploying".
set -euo pipefail

ROOT=/srv/caresense
APP=$ROOT/app
VENV=$ROOT/venv
WEB=$ROOT/web
ENV_FILE=/etc/caresense/caresense.env

as_app() { runuser -u caresense -- "$@"; }

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
[ -r "$ENV_FILE" ] || {
    echo "Missing $ENV_FILE - copy deploy/caresense.env.example there and fill it in." >&2
    exit 1
}

# Read the settings without letting the shell interpret them: a value such as
# "CareSense <no-reply@...>" is fine in the file and a syntax error in `source`.
while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in '' | '#'*) continue ;; esac
    export "$line"
done < "$ENV_FILE"

echo "==> Backend dependencies"
[ -x "$VENV/bin/python" ] || as_app python3 -m venv "$VENV"
as_app "$VENV/bin/pip" install --quiet -e "$APP/Backend[intelligence,document,server]"

echo "==> Database schema, and the cache table rate limits are counted in"
cd "$APP/Backend"
as_app "$VENV/bin/python" manage.py migrate --noinput
as_app "$VENV/bin/python" manage.py createcachetable

echo "==> Frontend (the build refuses to run if a VITE_ setting is missing)"
cd "$APP/Frontend"
as_app pnpm install --frozen-lockfile
as_app pnpm --filter @workspace/caresense-ai run build
mkdir -p "$WEB"
rsync -a --delete "$APP/Frontend/artifacts/caresense-ai/dist/public/" "$WEB/"

echo "==> Services"
install -m 644 "$APP"/deploy/systemd/*.service "$APP"/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --quiet caresense-intelligence caresense-api caresense-worker caresense-backup.timer
systemctl restart caresense-intelligence caresense-api caresense-worker
systemctl start caresense-backup.timer

echo "==> Caddy"
sed "s/CARESENSE_DOMAIN/$CARESENSE_DOMAIN/" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy

echo "==> Waiting for /readyz"
# As Caddy would send it: the real host name, and HTTPS already handled.
for _ in $(seq 1 30); do
    if curl -fsS -H "Host: $CARESENSE_DOMAIN" -H "X-Forwarded-Proto: https" \
            http://127.0.0.1:8000/readyz > /dev/null; then
        echo "Ready: https://$CARESENSE_DOMAIN"
        exit 0
    fi
    sleep 2
done
curl -sS -H "Host: $CARESENSE_DOMAIN" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/readyz || true
echo "Not ready. Look at: journalctl -u caresense-api -u caresense-worker -u caresense-intelligence" >&2
exit 1
