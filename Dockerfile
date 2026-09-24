# ── builder ──────────────────────────────────────────────────────────────────
# Alpine has no prebuilt (musllinux) wheel for psycopg2-binary, so it compiles
# from source here - these build deps never make it into the runtime image.
FROM ghcr.io/astral-sh/uv:python3.14-alpine AS builder

RUN apk add --no-cache gcc musl-dev postgresql-dev

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.14-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# libpq: psycopg2's runtime shared lib (not the -dev/build headers from the
# builder stage). tzdata: the app runs in Europe/London. nginx: fronts
# Django + Flower on a single port (8000).
RUN apk add --no-cache libpq tzdata nginx

WORKDIR /app
COPY --from=builder /app /app
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/nginx.conf /etc/nginx/http.d/default.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /var/log/supervisor

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf", "-n"]
