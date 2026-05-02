#!/usr/bin/env bash
# Runs ON the Hetzner VM during deploy. Pulls the latest backend image
# from GHCR, syncs frontend dist/ files, and reloads docker-compose-prod.

set -euo pipefail

cd /opt/vaultchain

# Pass the env file directly to docker compose. Don't `export $(... xargs)` —
# xargs splits values on whitespace, so EMAIL_FROM='VaultChain <noreply@...>'
# (legit RFC-5322 with display name) gets mangled into just "VaultChain" plus
# a `<noreply@...>` shell redirect, leaving EMAIL_FROM empty inside compose.
COMPOSE=(docker compose -f docker-compose-prod.yml --env-file /etc/vaultchain/env)

echo "[deploy-server] pulling backend image..."
"${COMPOSE[@]}" pull api worker

echo "[deploy-server] applying migrations..."
"${COMPOSE[@]}" run --rm api alembic upgrade head

echo "[deploy-server] reloading services..."
"${COMPOSE[@]}" up -d --remove-orphans

echo "[deploy-server] reloading caddy..."
"${COMPOSE[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile || true

echo "[deploy-server] done."
"${COMPOSE[@]}" ps
