# Changelog

All notable changes to this project will be documented in this file.

The format is based on \[Keep a Changelog],
and this project adheres to \[Semantic Versioning].

## [Unreleased]

### Added

- 🏷️ Standard OCI image labels on the Docker image (source, licenses, version, revision, created, etc.) - fixes GHCR/Renovate having no repo link for the published image

### Changed

- 🔧 Reworked the release pipeline to fix duplicate runs and half-built releases going live

## [0.0.3] - 2026-09-26

### Added

- 🚧 Branded 400/403/404/500 error pages

### Changed

- 🪶 Much lighter container — nginx and always-on Flower are gone, Celery beat runs inside the worker, and Celery uses a single-process pool. Idle memory down from ~677Mi to ~200Mi.
- ⬆️ Upgraded Django 5.2 → 6.0 (highest version django-celery-beat currently supports)
- 🤖 Dependency tracking improvements — Renovate now checks Mealie for new versions weekly (Mondays, 8am UTC) instead of continuously

## [0.0.2] - 2026-09-25

### Fixed

- 🔧 CI and release lifecycle cleanup — correct Docker image version on pre-releases, no more stray `.gitignore` release asset, releases now fail loudly instead of publishing with an empty changelog, and releases reliably trigger end-to-end

## [0.0.1] - 2026-09-24

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

<!-- Versions -->

[Unreleased]: https://github.com/afonsoc12/cookistash/compare/v0.0.3...HEAD

[0.0.3]: https://github.com/afonsoc12/cookistash/compare/v0.0.2...v0.0.3

[0.0.2]: https://github.com/afonsoc12/cookistash/compare/v0.0.1...v0.0.2

[0.0.1]: https://github.com/afonsoc12/cookistash/releases/tag/v0.0.1
