# Multi-stage backend deploy image — placeholder.
# phase1-deploy-001 finalizes the production-ready Dockerfile.

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_VIRTUALENVS_CREATE=false
RUN pip install "poetry==$POETRY_VERSION"

FROM base AS deps
WORKDIR /app
COPY backend/pyproject.toml backend/poetry.lock ./
RUN poetry install --only main --no-root --no-interaction

FROM base AS runtime
WORKDIR /app
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "vaultchain.main:app", "--host", "0.0.0.0", "--port", "8000"]
