<p align="center">
  <img src="cookistash/cookidoo/static/cookidoo/img/icon.png" alt="Cookistash" width="140">
</p>

# Cookistash

[![Build](https://img.shields.io/github/actions/workflow/status/afonsoc12/cookistash/release.yml?label=Build&logo=githubactions&logoColor=white)](https://github.com/afonsoc12/cookistash/actions/workflows/release.yml)
[![Coverage](https://img.shields.io/codecov/c/github/afonsoc12/cookistash?label=coverage&logo=codecov&logoColor=white)](https://codecov.io/gh/afonsoc12/cookistash)
[![Version](https://img.shields.io/github/v/release/afonsoc12/cookistash?label=version&color=green&logo=git&logoColor=white)](https://github.com/afonsoc12/cookistash/releases/latest)

> 🥘 Scrapes recipes from [Cookidoo](https://cookidoo.thermomix.com/) (Bimby/Thermomix) — with optional sync to [Mealie](https://mealie.io/).

**Cookistash** is a Cookidoo recipe scraper first. Sending recipes to Mealie is an addon that only switches on once you configure a Mealie source — no Mealie instance required to just scrape and keep recipes.

## ✨ Features

- 🔎 **Scrape by ID or link** — paste a Cookidoo recipe URL or ID, get back parsed ingredients, instructions, nutrition, categories, tags and tools
- 🔗 **Optional Mealie sync** — push any scraped recipe to a self-hosted Mealie instance; only active once configured, never required
- 🧠 **Correctly-split ingredients** — quantity/unit/food built from Cookidoo's own structured data, not Mealie's English-oriented NLP parser (which mis-segments non-English units with high confidence)
- ♻️ **Idempotent sync** — re-sending an unchanged recipe is a no-op (content-hash based), so scheduled rescrapes don't hammer Mealie's API for nothing
- ⏰ **Scheduled rescrapes** — a nightly job keeps stale recipes fresh, schedule editable from the admin
- 🖥️ **Explorer UI** — browse scraped recipes, see sync status, re-scrape or send-to-Mealie with one click, drill into raw scraped JSON
- 🎨 **Modern admin** — Django admin re-themed with Unfold, task results and periodic tasks linked back to the recipe they belong to
- 🐳 **Single, lightweight container** — one small image (~115 MB), runs comfortably on modest hardware

## 🚀 Quick Start

```bash
docker compose up --build -d
```

This starts:

| Service | Purpose | URL |
|---|---|---|
| `app` | The web app + background worker | [localhost:8000](http://localhost:8000) (UI + Admin) |
| `postgres` | Database (separate `cookistash` and `mealie` DBs) | — |
| `redis` | Celery broker | — |
| `mealie` | Recipe manager (optional, for sync) | [localhost:9000](http://localhost:9000) |

Migrations run automatically on container start.

### First-time setup

1. Set `COOKIDOO_EXPLORE_URL` (see below) and restart — the Cookidoo source is set up automatically, no admin step needed.
2. *(Optional)* To enable Mealie sync: log into Mealie with the default admin (`changeme@example.com` / `MyPassword`), change the password, generate an API token (Profile → API Tokens), then set `MEALIE_API_URL`/`MEALIE_API_TOKEN` (see below) and restart.
3. Use the UI to scrape a recipe by ID or pasted link, or browse **Discover**. **Send to Mealie** only appears once a Mealie source is configured.

## ⚙️ Configuration

All configuration is via environment variables (see `docker-compose.yml`).

| Variable | Description | Default |
|---|---|---|
| `COOKIDOO_EXPLORE_URL` | Your Cookidoo market's "explore" page URL, e.g. `https://cookidoo.pt/foundation/pt-PT/explore` | unset — scraping is disabled until this is set |
| `MEALIE_API_URL` / `MEALIE_API_TOKEN` | Mealie's API URL (e.g. `http://mealie:9000`) and an API token from Mealie's UI | unset — Mealie sync stays disabled until both are set |
| `MEALIE_PUBLIC_URL` / `MEALIE_GROUP_SLUG` | Browser-facing Mealie URL (for links in the UI) and your Mealie group slug | unset / `home` |
| `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_PORT` | Postgres connection | `localhost` / `cookistash` / `postgres` / `postgres` / `5432` |
| `CELERY_BROKER_URL` | Redis broker URL | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `django-db` |
| `DEBUG` | Django debug mode | `true` |
| `SECRET_KEY` | Signs sessions/CSRF tokens | unset — auto-generated and persisted on first run, no need to set it yourself |
| `DATA_DIR` | Where persistent state is stored, so it survives container upgrades | `/data` (bind-mounted to `./tmp/docker-data/app-data`) |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | `*` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated origins (with scheme) trusted for form submissions — set this if you're behind a reverse proxy | unset |
| `AUTO_ADMIN_LOGIN` | Skip the admin login form, auto-authenticate as the superuser | `true` — **only safe on localhost/private networks**, set `false` if ever exposed |

You don't need to set `SECRET_KEY` yourself (see above), but if you'd rather pin one explicitly, generate a long, cryptographically random one with:

```bash
openssl rand -hex 64
```

## 🖥️ UI

Lists scraped recipes with their scrape/sync status. Click a recipe for parsed ingredients, instructions, nutrition, categories/tags/tools, and the raw scraped JSON. Each row has:

- **↻ Re-scrape** — re-fetches the recipe from Cookidoo
- **→ Send to Mealie** — transforms the latest scrape and pushes it to Mealie (only shown when Mealie is configured)

## 🗺️ Roadmap

- [x] Browse/search Cookidoo's catalog and import without needing a recipe ID first — see **Discover**
- [ ] Bulk import (import more than one recipe at a time)
- [ ] Retry/backoff on background jobs and outbound requests
- [ ] Delete a recipe from Mealie directly from Cookistash

## 📄 License

**Copyright © 2026 [Afonso Costa](https://github.com/afonsoc12)**

Licensed under the MIT License. See the [LICENSE](./LICENSE) file for details.
