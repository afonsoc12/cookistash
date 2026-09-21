<p align="center">
  <img src="cookistash/cookidoo/static/cookidoo/img/icon.png" alt="Cookistash" width="140">
</p>

# Cookistash

[![Build](https://img.shields.io/github/actions/workflow/status/afonsoc12/cookistash/ci.yml?label=Build&logo=githubactions&logoColor=white)](https://github.com/afonsoc12/cookistash/actions/workflows/ci.yml)

> 🥘 Scrapes recipes from [Cookidoo](https://cookidoo.thermomix.com/) (Bimby/Thermomix) — with optional sync to [Mealie](https://mealie.io/).

**Cookistash** is a Cookidoo recipe scraper first. Sending recipes to Mealie is an addon that only switches on once you configure a Mealie source — no Mealie instance required to just scrape and keep recipes.

## ✨ Features

- 🔎 **Scrape by ID or link** — paste a Cookidoo recipe URL or ID, get back parsed ingredients, instructions, nutrition, categories, tags and tools
- 🔗 **Optional Mealie sync** — push any scraped recipe to a self-hosted Mealie instance; only active once configured, never required
- 🧠 **Correctly-split ingredients** — quantity/unit/food built from Cookidoo's own structured data, not Mealie's English-oriented NLP parser (which mis-segments non-English units with high confidence)
- ♻️ **Idempotent sync** — re-sending an unchanged recipe is a no-op (content-hash based), so scheduled rescrapes don't hammer Mealie's API for nothing
- ⏰ **Scheduled rescrapes** — nightly job (django-celery-beat, DB-backed and editable in-admin) keeps stale recipes fresh
- 🖥️ **Explorer UI** — browse scraped recipes, see sync status, re-scrape or send-to-Mealie with one click, drill into raw scraped JSON
- 🎨 **Modern admin** — Django admin re-themed with Unfold, task results and periodic tasks linked back to the recipe they belong to
- 🐳 **Single container** — Django + Celery worker + Celery beat + Flower, one image, ~115 MB (Alpine + Python 3.14)

## 🚀 Quick Start

```bash
docker compose up --build -d
```

This starts:

| Service | Purpose | URL |
|---|---|---|
| `app` | Django + Celery worker + beat + Flower, fronted by nginx (supervisord) | [localhost:8000](http://localhost:8000) (UI + Admin), [localhost:8000/flower/](http://localhost:8000/flower/) (Celery/Flower) |
| `postgres` | Database (separate `cookistash` and `mealie` DBs) | — |
| `redis` | Celery broker | — |
| `mealie` | Recipe manager (optional, for sync) | [localhost:9000](http://localhost:9000) |

Migrations run automatically on container start.

### First-time setup

1. Create a `cookidoo.Source` in the Django admin ([localhost:8000/admin](http://localhost:8000/admin/)) — Cookidoo site URL + locale, marked default. That's all that's required to scrape.
2. *(Optional)* To enable Mealie sync: log into Mealie with the default admin (`changeme@example.com` / `MyPassword`), change the password, generate an API token, then create a `mealie.Source` in the admin (`http://mealie:9000` as the API URL from inside the container network, plus the token, marked default).
3. Use the UI to scrape a recipe by ID or pasted link. **Send to Mealie** only appears once a Mealie source is configured.

## ⚙️ Configuration

All configuration is via environment variables (see `docker-compose.yml`).

| Variable | Description | Default |
|---|---|---|
| `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_PORT` | Postgres connection | `localhost` / `cookistash` / `postgres` / `postgres` / `5432` |
| `CELERY_BROKER_URL` | Redis broker URL | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `django-db` |
| `DEBUG` | Django debug mode | `true` |
| `SECRET_KEY` | Django secret key | insecure dev default — **set this in production** |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | `*` |
| `AUTO_ADMIN_LOGIN` | Skip the admin login form, auto-authenticate as the superuser | `true` — **only safe on localhost/private networks**, set `false` if ever exposed |

## 🖥️ UI

Lists scraped recipes with their scrape/sync status. Click a recipe for parsed ingredients, instructions, nutrition, categories/tags/tools, and the raw scraped JSON. Each row has:

- **↻ Re-scrape** — re-fetches the recipe from Cookidoo
- **→ Send to Mealie** — transforms the latest scrape and pushes it to Mealie (only shown when Mealie is configured)

## ⏰ Scheduled Jobs

Managed via django-celery-beat — DB-backed, editable at `/admin/django_celery_beat/periodictask/` without a redeploy. A nightly rescrape job (03:00, recipes not scraped in 7 days) is auto-seeded on first migrate.

## 🐳 Docker Details

Multi-stage build, Alpine + Python 3.14. `psycopg2` compiles from source in the builder stage (no musllinux wheel available) and never ships in the runtime image. ~115 MB total.

```
ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf", "-n"]
```

## 🛠️ Development

```bash
uv sync --all-groups   # install app + dev deps (ruff, mypy, pytest-cov, pytest-bdd)
uv run ruff format     # format
uv run ruff check      # lint
uv run mypy cookistash/
```

## ✅ Tests

```bash
uv run pytest -m "not e2e"   # unit tests, with coverage (see htmlcov/index.html)
```

Requires a reachable Postgres (`DB_HOST=localhost DB_NAME=cookistash` works against the docker-compose `postgres` service).

`tests/e2e/` runs the real scrape → transform → sync pipeline (pytest-bdd/Gherkin) against live docker-compose services — see `tests/e2e/README.md`. Excluded from the default run and from CI; run explicitly with `-m e2e`.

## 🔁 CI

`.github/workflows/ci.yml` runs ruff (format + lint), mypy, the unit test suite with coverage (uploaded as a build artifact), and builds the Docker image. e2e tests are skipped (they need live services CI doesn't spin up).

## 🗺️ Roadmap

- [ ] Batch/collection import (`CookidooClient.get_country_recipes()` exists, no task/UI wrapper yet)
- [ ] Retry/backoff on Celery tasks and outbound HTTP calls
- [ ] Rate limiting on collection scraping
- [ ] Search by ingredient/category/tag in the Explorer (currently name only)

## 📄 License

**Copyright © 2026 [Afonso Costa](https://github.com/afonsoc12)**

Licensed under the MIT License. See the [LICENSE](./LICENSE) file for details.
