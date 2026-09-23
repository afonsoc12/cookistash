# CLAUDE.md

This file provides guidance to AI agents working with code in this repository. Keep it current as the project evolves: add sections for new tooling/workflows as they're introduced, and remove or update anything that no longer reflects reality.

## Project Overview

**Cookistash** scrapes recipes from Cookidoo (Bimby/Thermomix) and optionally syncs them to a self-hosted Mealie instance. It's a single Django app (+ Celery worker/beat + Flower), packaged into one Docker image. Mealie sync is entirely optional — it only activates once a Mealie source is configured; scraping/browsing works standalone.

Two Django apps:
- `cookistash/cookidoo/` — scrapes Cookidoo, stores raw + parsed recipe data (`Source`, recipe models), the Explorer UI (`views.py`, `templates/`), Celery tasks for scraping (`tasks.py`).
- `cookistash/mealie/` — Mealie API client (`client.py`), transforms scraped Cookidoo data into Mealie's shape (`transformer.py`), pushes recipes via `Source`/`Recipe`/etc. models mirroring Mealie's own schema.

Both apps auto-create/update their single `Source` row on every container start via management commands (`sync_cookidoo_source`, `sync_mealie_source`), driven by env vars — no admin setup step. Only one Cookidoo source and one Mealie source are supported at a time (see README for why).

## Commands

```bash
# Install dependencies (app + dev deps: ruff, mypy, pytest-cov, pytest-bdd, pre-commit)
uv sync --locked --all-groups

# --- Running it ---

# Full stack via Docker - closest to how it actually runs, but no hot reload
docker compose up --build -d

# Django's dev server against dockerized Postgres/Redis - hot reload, faster Python/template iteration
docker compose up -d postgres redis   # just the backing services
uv run python manage.py migrate
uv run python manage.py sync_cookidoo_source   # if COOKIDOO_EXPLORE_URL is set
uv run python manage.py runserver
# DB_HOST/CELERY_BROKER_URL already default to localhost, matching docker-compose's exposed ports.

# --- Linting, type checking, tests ---

uv run ruff format          # auto-fix
uv run ruff format --check  # CI check
uv run ruff check --fix

uv run mypy cookistash/

# Unit tests (no real Postgres needed - runs against in-memory SQLite)
# CI=true is set automatically in GitHub Actions, so no flag needed there;
# locally, opt in explicitly with DB_ENGINE=sqlite3.
DB_ENGINE=sqlite3 uv run pytest -m "not e2e"

# e2e tests (needs real Postgres + Mealie from docker-compose)
docker compose up -d postgres redis mealie
uv run pytest -m e2e   # see tests/e2e/README.md

# --- Pre-commit (.pre-commit-config.yaml) ---

uv run pre-commit install       # one-time, per clone - wires the git hook
uv run pre-commit run --all-files  # run every hook against the whole repo on demand
# Runs on every `git commit`: trailing-whitespace/EOF/yaml/json/toml checks, ruff format,
# ruff check --fix, mypy, and the unit test suite - which enforces the >=90% coverage gate
# (fail_under = 90 in pyproject.toml) and blocks the commit if coverage drops below it.
```

All lint/type-check/test artifacts (`.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `coverage.xml`, `htmlcov/`) are written under `build/` (configured in `pyproject.toml`), gitignored, never scattered across the repo root.

## Testing

- **Unit tests** (`tests/unit/`) run against Django's ORM but against an in-memory SQLite DB instead of the real Postgres settings — no docker-compose needed, no services to spin up. `cookistash/settings.py` swaps the DB engine automatically when `CI=true` (set by GitHub Actions) or `DB_ENGINE=sqlite3` is set explicitly (for running the same suite locally). CI runs these on every push and PR (`.github/workflows/ci.yml`).
  - One exception: `tests/unit/mealie/test_models.py::TestModelMealieApi` dynamically creates/drops a table via `schema_editor`, which SQLite refuses to do inside the implicit per-test transaction `django_db` normally wraps tests in — that class overrides with `pytest.mark.django_db(transaction=True)`.
  - Coverage config (`[tool.coverage.*]` in `pyproject.toml`) requires ≥90% and fails the run otherwise.
- **e2e tests** (`tests/e2e/`) exercise the real scrape → transform → sync pipeline against live Postgres/Mealie from docker-compose — only the network call to Cookidoo itself is stubbed with fixture JSON (`data/recipes/`). Excluded by default (`-m "not e2e"`), never run in CI; see `tests/e2e/README.md`.

## CI (`.github/workflows/ci.yml`)

Runs on every push (including `main`) and PR, draft or not: ruff format/check, mypy, unit tests with coverage, then posts a coverage summary (badge, per-file breakdown, links to the `htmlcov`/`coverage.xml` artifact and to Codecov) to the job summary. Coverage is also uploaded to [Codecov](https://codecov.io/gh/afonsoc12/cookistash) for the richer hosted UI (trends, sunburst, PR diff coverage) — authenticated via OIDC (`use_oidc: true` + the job's `id-token: write` permission), not a static token; Codecov's plain public-repo tokenless bypass is being retired in favor of this. No Postgres service needed — `settings.py` auto-detects `CI=true`. Doesn't build the Docker image — that only happens in `release.yml` (on `main`/version tags), which builds and pushes the real multi-arch image to GHCR.

## Configuration

Everything is env-var driven — see the README's Configuration table for the full list (`COOKIDOO_EXPLORE_URL`, `MEALIE_API_URL`/`MEALIE_API_TOKEN`, `DB_*`, `CELERY_*`, `SECRET_KEY`, `DATA_DIR`, etc.). `docker-compose.yml` is the reference for local dev defaults.

## Pre-commit (`.pre-commit-config.yaml`)

Local-only, not run in CI (CI runs the same checks directly, see above). Install once with `uv run pre-commit install`; every `git commit` then runs ruff format, ruff check, mypy, and the unit test suite, which fails the commit if coverage drops below 90%.

## Dependency updates

Renovate is enabled (`renovate.json`, `config:recommended` preset) — PRs are labeled `renovate`.
