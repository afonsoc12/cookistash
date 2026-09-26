# Alpine has no prebuilt (musllinux) wheel for psycopg2-binary, so it compiles
# from source here - these build deps never make it into the runtime image.
FROM ghcr.io/astral-sh/uv:python3.14-alpine AS builder

RUN apk add --no-cache gcc musl-dev postgresql-dev

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

FROM python:3.14-alpine

# Passed via --build-arg from build.yml; "n/a" default covers a plain `docker build .`.
ARG VERSION=n/a
ARG REVISION=n/a
ARG BUILD_DATE=n/a

# OCI standard labels: https://github.com/opencontainers/image-spec/blob/main/annotations.md
LABEL org.opencontainers.image.title="Cookistash" \
    org.opencontainers.image.description="🥘 Stash your Cookidoo recipes and sync them to Mealie." \
    org.opencontainers.image.source="https://github.com/afonsoc12/cookistash" \
    org.opencontainers.image.url="https://github.com/afonsoc12/cookistash/pkgs/container/cookistash?tag=${VERSION}" \
    org.opencontainers.image.documentation="https://github.com/afonsoc12/cookistash/blob/main/README.md" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.authors="afonsoc12" \
    org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.revision="${REVISION}" \
    org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# libpq: psycopg2's runtime shared lib (not the -dev/build headers from the
# builder stage). tzdata: the app runs in Europe/London. Static files are
# served by gunicorn + WhiteNoise directly - no nginx needed.
RUN apk add --no-cache libpq tzdata

WORKDIR /app
COPY --from=builder /app /app
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /var/log/supervisor

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf", "-n"]
