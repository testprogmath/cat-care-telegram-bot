#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  . ./.env
  set +a
fi

HOST="${DEPLOY_HOST:?set DEPLOY_HOST, e.g. deploy@203.0.113.10}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE_DIR="${DEPLOY_DIR:-~/apps/skrypka-telegram-bot}"

echo "==> Syncing files..."
rsync -az --delete \
  --exclude='.git' --exclude='.venv' --exclude='data/' --exclude='.env' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='dist/' --exclude='.claude' \
  -e "ssh -i $KEY" \
  . "$HOST:$REMOTE_DIR"

echo "==> Building and restarting..."
ssh -i "$KEY" "$HOST" "
  cd $REMOTE_DIR
  docker compose build --pull
  docker compose up -d
  docker compose ps
"

echo "==> Done. Logs: ssh -i $KEY $HOST 'cd $REMOTE_DIR && docker compose logs -f'"
