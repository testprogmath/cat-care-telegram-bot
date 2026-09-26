#!/usr/bin/env bash
set -euo pipefail

HOST="deploy@204.168.217.208"
KEY="$HOME/.ssh/id_ed25519"
REMOTE_DIR="~/apps/skrypka-telegram-bot"

echo "==> Syncing files..."
rsync -az --delete \
  --exclude='.git' --exclude='.venv' --exclude='data/' \
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
