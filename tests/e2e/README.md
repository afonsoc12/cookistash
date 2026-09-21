# E2E tests

Exercise the real scrape -> transform -> sync pipeline against live
docker-compose services (Postgres, Mealie). Only the Cookidoo HTTP call is
stubbed (fixture JSON from `data/recipes/`) - everything else, including
the Mealie HTTP API, is real.

## Running

```bash
docker compose up -d postgres redis mealie
DB_HOST=localhost DB_NAME=cookistash uv run pytest tests/e2e/ -m e2e
```

Skipped in CI by default (`-m "not e2e"`) since they need the docker-compose
stack running.
