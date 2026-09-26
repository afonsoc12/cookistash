# CLAUDE.md

This file provides guidance to AI agents working with code in this repository. Keep it current as the project evolves: add sections for new tooling/workflows as they're introduced, and remove or update anything that no longer reflects reality.

## Project Overview

**Cookistash** scrapes recipes from Cookidoo (Bimby/Thermomix) and optionally syncs them to a self-hosted Mealie instance. It's a single Django app (gunicorn + WhiteNoise) plus one Celery worker with beat baked in and a `solo` pool (`celery worker -B --pool=solo` - single process, no per-CPU-core forking, since task volume here doesn't need it), packaged into one Docker image, deliberately kept minimal (no nginx, no always-on Flower) so it fits small compute limits. Mealie sync is entirely optional — it only activates once a Mealie source is configured; scraping/browsing works standalone.

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

Runs on every push to `main` and every PR (draft or not): ruff format/check, mypy, unit tests with coverage, then posts a coverage summary (badge, per-file breakdown, links to the `htmlcov`/`coverage.xml`/`junit.xml` artifact and to Codecov) to the job summary. Coverage and test results are also uploaded to [Codecov](https://codecov.io/gh/afonsoc12/cookistash) for the richer hosted UI (trends, sunburst, PR diff coverage, flaky/slow test tracking) — authenticated via OIDC (`use_oidc: true` + the job's `id-token: write` permission), not a static token; Codecov's plain public-repo tokenless bypass is being retired in favor of this. No Postgres service needed — `settings.py` auto-detects `CI=true`. Doesn't build the Docker image itself — that happens in `build.yml`.

## Releases (`.github/workflows/build.yml` + `dev-release.yml` + `prepare-release.yml`)

Three files, two independent pipelines that happen to share the actual build steps:

- **`build.yml`** is a reusable workflow (`workflow_call`) - it just builds whatever's checked out: `uv build` for the wheel/sdist (uploaded as a `dist` artifact) and a multi-arch (`linux/amd64,linux/arm64`) Docker image pushed to the tags it's given. It never runs `uv version <value>` to rewrite the version - the wheel and the Docker image always reflect exactly what's committed, never a build-time-only synthetic value. Both pipelines below call it.

- **`dev-release.yml`** triggers on every push to `main` (and `workflow_dispatch`). Computes a `v{version}-dev+{sha}` tag and `:dev`/`:{version}-dev-{sha}` Docker tags from whatever's currently committed, calls `build.yml`, then creates a GitHub **prerelease** with the wheel/sdist attached. This is the continuous "does main still build" signal - it never creates a real release or a `:latest`/`:{version}` Docker tag.

- **`prepare-release.yml`** (`workflow_dispatch`, pick a `patch`/`minor`/`major` bump) is the actual release pipeline, entirely self-contained in one workflow run:
  1. `uv version --bump <type>` bumps `pyproject.toml`/`uv.lock`; `release-flow/keep-a-changelog-action`'s `bump` command (pinned `@v3`) converts `CHANGELOG.md`'s `[Unreleased]` section using that same bump keyword - `@v3`'s `version` input only accepts a keyword (`major`/`minor`/`patch`/...), not an explicit version, despite what its `main`-branch (unreleased) docs claim.
  2. Commits and pushes straight to `main`, with `[skip ci]` in the commit message - see below for why.
  3. Calls `build.yml` directly (same reusable workflow `dev-release.yml` uses) with the real `:{version}`/`:latest` tags - by this point `pyproject.toml` already has the bumped version committed, so no version mutation is needed here either.
  4. Once that succeeds, creates the actual GitHub Release - tag, notes, wheel/sdist already built and attached, `target_commitish: main` - published immediately, since nothing about it is left to finish afterward.

**Why the commit message has `[skip ci]`:** the release commit landing on `main` would otherwise also trigger `dev-release.yml`'s push path, producing a pointless `:dev` prerelease for a commit that's simultaneously becoming the real release seconds later. GitHub natively skips any `push`/`pull_request`-triggered workflow run when the commit message contains `[skip ci]` (or `[ci skip]`/`[no ci]`/`[skip actions]`/`[actions skip]`) - see [Skipping workflow runs](https://docs.github.com/en/actions/managing-workflow-runs/skipping-workflow-runs). `prepare-release.yml`'s own run is unaffected (it's `workflow_dispatch`, not `push`).

**Why the real release is built entirely inside `prepare-release.yml`** rather than being triggered by a separate event (a tag push, a published release, etc.): earlier attempts at that ran into pushing a commit and a tag together firing two separate `push` events for the same commit (GitHub registers one ref-update event per ref, `--atomic` doesn't change this), and even a `release: published` trigger still meant the release object existed before anything had actually built, or needed a fragile draft/publish dance to avoid that. Having `prepare-release.yml` call `build.yml` directly as a job in the same run sidesteps all of it - there's exactly one workflow run for a real release, the tag/release only gets created after the build has already succeeded, and there's no cross-workflow event timing to get wrong.

A tag can't just be created on a PR branch and merged in - this repo only allows squash/rebase merges (`mergeCommitAllowed: false`), which rewrite commits to a new SHA, orphaning any tag pointed at the old one. Hence pushing directly to `main` instead of going through a PR.

`prepare-release.yml` checks out and pushes using the `RELEASE_PAT` repo secret instead of the default `GITHUB_TOKEN`, matching every other automation-pushed commit to `main` in this repo - not because this specific push needs to trigger anything (`[skip ci]` ensures it doesn't). The final release-creation step uses the default `GITHUB_TOKEN` instead, since nothing needs to react to a release being published anymore. `RELEASE_PAT` must be a fine-grained personal access token scoped to this repository only, with **Contents: Read and write** permission.

PRs that change behavior should add an entry to `CHANGELOG.md`'s `[Unreleased]` section - `dev-release.yml` fails outright if it's empty when a push lands on `main` (see above), and `prepare-release.yml`'s changelog-bump step has the same `fail-on-empty-release-notes` guard. Keep entries short and human-readable, not a dump of commit messages or internal implementation detail.

## Configuration

Everything is env-var driven — see the README's Configuration table for the full list (`COOKIDOO_EXPLORE_URL`, `MEALIE_API_URL`/`MEALIE_API_TOKEN`, `DB_*`, `CELERY_*`, `SECRET_KEY`, `DATA_DIR`, etc.). `docker-compose.yml` is the reference for local dev defaults.

## Pre-commit (`.pre-commit-config.yaml`)

Local-only, not run in CI (CI runs the same checks directly, see above). Install once with `uv run pre-commit install`; every `git commit` then runs ruff format, ruff check, mypy, and the unit test suite, which fails the commit if coverage drops below 90%.

## Comments

Default to no comment. Only add one when the code can't explain itself — a non-obvious constraint, a workaround for a specific bug, a reason a simpler approach doesn't work. Never comment what the code already says (`# increment counter` above `counter += 1`), never leave commented-out code, never restate a docstring line-by-line. When a comment is warranted, keep it short and write it for a human who's new to the file, not future-you.

## Dependency updates

Renovate is enabled (`renovate.json`, `config:recommended` preset) — PRs are labeled `renovate`.
