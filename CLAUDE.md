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

## Releases (`.github/workflows/build.yml` + `dev-release.yml` + `release.yml`)

Three files, two independent pipelines that happen to share the actual build steps:

- **`build.yml`** is a reusable workflow (`workflow_call`) - it checks out `inputs.ref` (always explicit, never the caller's default `github.sha` - see below) and builds it: `uv build` for the wheel/sdist (uploaded as a `dist` artifact) and a multi-arch (`linux/amd64,linux/arm64`) Docker image pushed to the tags it's given. For a real release it never runs `uv version <value>` to rewrite the version - the wheel and the Docker image always reflect exactly what's committed. The one exception is `inputs.version_suffix`, used only by `dev-release.yml` to give otherwise-identical dev wheels a unique, non-committed local version identifier - without it every dev build between two releases would produce a wheel with the same filename despite different content, since the committed version doesn't change until the next real release.

- **`dev-release.yml`** triggers on every push to `main` (and `workflow_dispatch`) - it builds the wheel/sdist (uploaded only as a workflow artifact, never a GitHub Release - nothing consumes it since this app ships as a Docker image, not a PyPI package) and pushes a rolling `ghcr.io/afonsoc12/cookistash:dev` Docker image plus a `:{version}-dev-{sha}` pinned one. This is just the continuous "does main still build" signal - no GitHub release object, no `:latest`/`:{version}` tag.

- **`release.yml`** (`workflow_dispatch`, pick a `patch`/`minor`/`major` bump) is the actual release pipeline, entirely self-contained in one workflow run:
  1. Before bumping anything, checks `git ls-remote` for a `vX.Y.Z` tag matching the version this bump would produce - if it already exists, fails loudly instead of silently bumping past a version whose release previously failed partway through and was never cleaned up.
  2. `uv version --bump <type>` bumps `pyproject.toml`/`uv.lock`; `release-flow/keep-a-changelog-action`'s `bump` command (pinned `@v3`) converts `CHANGELOG.md`'s `[Unreleased]` section using that same bump keyword - `@v3`'s `version` input only accepts a keyword (`major`/`minor`/`patch`/...), not an explicit version, despite what its `main`-branch (unreleased) docs claim.
  3. Commits and pushes straight to `main`, with `[skip ci]` in the commit message (see below), and captures the pushed commit's exact SHA as a job output.
  4. Runs `ci.yml` against that exact SHA - a real release is never built from code that hasn't been linted/type-checked/tested, even though the commit is `[skip ci]`'d from the push-triggered path.
  5. Calls `build.yml` (same reusable workflow `dev-release.yml` uses) pinned to that same SHA, with a Docker *staging* tag only (`:build-{sha}`) and no version suffix - `pyproject.toml` already has the bumped version committed by this point, so the wheel/sdist need no mutation either.
  6. Creates the actual GitHub Release - tag, notes, wheel/sdist already built and attached, `target_commitish` pinned to the exact commit SHA (not the `main` branch name, which could move if something else gets pushed while the build is running) - then immediately verifies via the API that the release exists and both a `.whl` and a `.tar.gz` are attached, failing loudly if not rather than reporting success on a release that isn't actually complete.
  7. Only once that's verified, promotes the staging Docker image to `:latest`/`:{version}` via `docker buildx imagetools create` (copies the existing multi-arch manifest to new tags - no rebuild, byte-identical to what was just built and verified). Nothing public-facing (`:latest`/`:{version}`) exists until the release behind it is confirmed real.

**Why every job pins an explicit `ref`/`target_commitish` to a SHA, never a branch name or the implicit default:** `actions/checkout`'s default (no `ref:` given) resolves to `github.sha`, which is fixed at the moment the workflow *run* started - for `release.yml` (`workflow_dispatch`), that's the commit that existed *before* the version-bump commit in step 2 above was even pushed. Without pinning, `build.yml` would silently build the pre-bump code while believing it matches the just-bumped `pyproject.toml`/`CHANGELOG.md` - exactly the inconsistency the whole "no version mutation in build.yml" design is meant to prevent. Capturing the real post-push SHA as a job output and threading it through every checkout and `target_commitish` closes that gap.

**Why the commit message has `[skip ci]`:** the release commit landing on `main` would otherwise also trigger `dev-release.yml`'s push path, producing a pointless dev build for a commit that's simultaneously becoming the real release seconds later. GitHub natively skips any `push`/`pull_request`-triggered workflow run when the commit message contains `[skip ci]` (or `[ci skip]`/`[no ci]`/`[skip actions]`/`[actions skip]`) - see [Skipping workflow runs](https://docs.github.com/en/actions/managing-workflow-runs/skipping-workflow-runs). `release.yml`'s own run is unaffected (it's `workflow_dispatch`, not `push`), and its own `ci` job (step 3 above) runs regardless.

**Why the real release is built entirely inside `release.yml`** rather than being triggered by a separate event (a tag push, a published release, etc.): earlier attempts at that ran into pushing a commit and a tag together firing two separate `push` events for the same commit (GitHub registers one ref-update event per ref, `--atomic` doesn't change this), and even a `release: published` trigger still meant the release object existed before anything had actually built, or needed a fragile draft/publish dance to avoid that. Having `release.yml` call `build.yml` directly as a job in the same run sidesteps all of it - there's exactly one workflow run for a real release, the tag/release only gets created after the build has already succeeded, and there's no cross-workflow event timing to get wrong.

A tag can't just be created on a PR branch and merged in - this repo only allows squash/rebase merges (`mergeCommitAllowed: false`), which rewrite commits to a new SHA, orphaning any tag pointed at the old one. Hence pushing directly to `main` instead of going through a PR.

`release.yml` uses the default `GITHUB_TOKEN` throughout, including for the push to `main` - `main` has no branch protection, and this push doesn't need to trigger anything else (the actual build/release happens via `needs:` job dependencies in this same run, not by anything reacting to the push). No PAT is required anywhere in this pipeline anymore.

`release.yml` also has a `concurrency: group: prepare-release` (no `cancel-in-progress`) so two accidental manual triggers queue instead of racing each other's version bump; `dev-release.yml` cancels its own in-progress run per-ref instead, since a newer commit's dev build makes an older one moot.

PRs that change behavior should add an entry to `CHANGELOG.md`'s `[Unreleased]` section - `release.yml`'s changelog-bump step has a `fail-on-empty-release-notes` guard, so an empty section blocks cutting a release. Keep entries to one line each, plain and human-readable - what changed and why it matters to someone running the app, not a dump of commit messages, internal implementation detail, or a design-doc-length explanation of how it was fixed.

## Configuration

Everything is env-var driven — see the README's Configuration table for the full list (`COOKIDOO_EXPLORE_URL`, `MEALIE_API_URL`/`MEALIE_API_TOKEN`, `DB_*`, `CELERY_*`, `SECRET_KEY`, `DATA_DIR`, etc.). `docker-compose.yml` is the reference for local dev defaults.

## Pre-commit (`.pre-commit-config.yaml`)

Local-only, not run in CI (CI runs the same checks directly, see above). Install once with `uv run pre-commit install`; every `git commit` then runs ruff format, ruff check, mypy, and the unit test suite, which fails the commit if coverage drops below 90%.

## Comments

Default to no comment. Only add one when the code can't explain itself — a non-obvious constraint, a workaround for a specific bug, a reason a simpler approach doesn't work. Never comment what the code already says (`# increment counter` above `counter += 1`), never leave commented-out code, never restate a docstring line-by-line. When a comment is warranted, keep it short and write it for a human who's new to the file, not future-you.

## Dependency updates

Renovate is enabled (`renovate.json`, `config:recommended` preset) — PRs are labeled `renovate`.
