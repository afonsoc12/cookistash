# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog],
and this project adheres to [Semantic Versioning].

## [Unreleased]

### Added

- 🔎 Scrape Cookidoo recipes by ID or link, with parsed ingredients/instructions/nutrition/categories/tags/tools
- 🔗 Optional Mealie sync — pushes scraped recipes to a self-hosted Mealie instance, only active once configured
- 🧠 Ingredients built directly from Cookidoo's structured data (quantity/unit/food), bypassing Mealie's unreliable NLP parser
- ♻️ Idempotent sync — content-hash based, unchanged recipes are skipped on re-send
- ⏰ Nightly rescrape job (django-celery-beat, DB-backed and editable in-admin)
- 🧭 Discover — browse Cookidoo's own catalog by category, market/country and keyword search, and import in one click
- 🌍 Cookidoo source auto-configured from `COOKIDOO_EXPLORE_URL` (domain + locale parsed from the market's own explore URL) — single-source only, since each Cookidoo market is a separate domain/API
- 🔗 Mealie source likewise auto-configured from `MEALIE_API_URL`/`MEALIE_API_TOKEN` (+ optional `MEALIE_PUBLIC_URL`/`MEALIE_GROUP_SLUG`), single-source only, re-syncs on every container start if the env vars change
- 🖥️ Explorer UI — recipe grid with scrape/sync status, re-scrape and send-to-Mealie actions, raw JSON viewer
- 🎨 Django admin re-themed with Unfold, using the app's own orange accent and icon, with a "Back to Cookistash" link; task results and periodic tasks linked back to their recipe
- 🌸 Flower (Celery monitoring) served under the same origin via nginx, linked from the UI
- 🐳 Single container (Django + Celery worker + beat + Flower + nginx via supervisord), Alpine + Python 3.14

<!-- Links -->

[Keep a Changelog]: https://keepachangelog.com/en/1.0.0/
[Semantic Versioning]: https://semver.org/spec/v2.0.0.html

<!-- Versions -->

[unreleased]: https://github.com/afonsoc12/cookistash/commits/master
