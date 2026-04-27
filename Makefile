.PHONY: help setup dev test format lint compose-up compose-down gen-manifest seed-demo

help:
	@echo "Targets:"
	@echo "  setup          - Install backend + frontend deps"
	@echo "  dev            - Run backend + both SPAs + compose stack"
	@echo "  test           - Run all tests (backend + frontend)"
	@echo "  format         - Format code (ruff + prettier)"
	@echo "  lint           - Lint code (ruff + mypy + import-linter + eslint)"
	@echo "  compose-up     - Start dev compose stack"
	@echo "  compose-down   - Stop dev compose stack"
	@echo "  gen-manifest   - Regenerate manifest.yaml from brief frontmatter"
	@echo "  seed-demo      - Seed demo data via cli/scripts/seed_admin.py"

setup:
	cd backend && poetry install --with dev
	pnpm install --frozen-lockfile

dev: compose-up
	@echo "Starting backend (uvicorn) + web + admin in parallel..."
	@(cd backend && poetry run uvicorn vaultchain.main:app --reload --port 8000) & \
	 (pnpm --filter web dev) & \
	 (pnpm --filter @vaultchain/admin dev) & \
	 wait

test:
	cd backend && poetry run pytest -v
	pnpm --filter web run test
	pnpm --filter @vaultchain/admin run test

format:
	cd backend && poetry run ruff format .
	pnpm exec prettier --write "**/*.{ts,tsx,json,md,yaml,yml}"

lint:
	cd backend && poetry run ruff check . && poetry run mypy src/vaultchain && poetry run lint-imports
	pnpm run lint

compose-up:
	docker compose -f docker-compose-dev.yml up -d

compose-down:
	docker compose -f docker-compose-dev.yml down

gen-manifest:
	python scripts/gen_manifest.py

seed-demo:
	cd backend && poetry run python ../cli/scripts/seed_admin.py
