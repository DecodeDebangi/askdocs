# API + widget + demo page. Runs on any Docker host; render.yaml deploys it to Render's free plan.
# Small hosts (Render free: 0.1 CPU, 512 MB): RERANK=none MODEL_THREADS=1, ~290 MB peak.
# With the reranker on as well it needs ~1 CPU and ~500 MB.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/app/models \
    PORT=7860

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv

WORKDIR /app
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY api/src ./src
RUN uv sync --frozen --no-dev

# Bake the embedding model into the image: free hosts have no persistent disk, so it would
# otherwise download on every cold start. (The reranker, off on small hosts, downloads on first use.)
RUN uv run --no-sync python -c "from askdocs.embed import model; model()"

RUN useradd -m -u 1000 app && chown -R app /app
USER app

EXPOSE 7860
CMD ["sh", "-c", "uv run --no-sync uvicorn askdocs.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
