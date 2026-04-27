#!/usr/bin/env bash
# Runs ON the Hetzner VM during deploy. Pulls the latest backend image
# from GHCR, syncs frontend dist/ files, and reloads docker-compose-prod.

set -euo pipefail

cd /opt/vaultchain
export $(grep -v '^#' /etc/vaultchain/env | xargs)

echo "[deploy-server] pulling backend image..."
docker compose -f docker-compose-prod.yml pull api worker

echo "[deploy-server] applying migrations..."
docker compose -f docker-compose-prod.yml run --rm api alembic upgrade head

echo "[deploy-server] reloading services..."
docker compose -f docker-compose-prod.yml up -d --remove-orphans

echo "[deploy-server] reloading caddy..."
docker compose -f docker-compose-prod.yml exec -T caddy caddy reload --config /etc/caddy/Caddyfile || true

echo "[deploy-server] done."
docker compose -f docker-compose-prod.yml ps
