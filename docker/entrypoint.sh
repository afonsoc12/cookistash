#!/bin/sh
set -e

echo "Waiting for database..."
until /app/.venv/bin/python -c "
import os, sys, psycopg2
try:
    psycopg2.connect(
        host=os.environ.get('DB_HOST', 'postgres'),
        port=os.environ.get('DB_PORT', '5432'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'postgres'),
        dbname='postgres',
    )
except Exception:
    sys.exit(1)
"; do
    sleep 1
done

echo "Running migrations..."
/app/.venv/bin/python manage.py migrate --noinput

echo "Syncing Cookidoo source..."
/app/.venv/bin/python manage.py sync_cookidoo_source

echo "Syncing Mealie source..."
/app/.venv/bin/python manage.py sync_mealie_source

echo "Collecting static files..."
/app/.venv/bin/python manage.py collectstatic --noinput

exec "$@"
