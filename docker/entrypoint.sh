#!/bin/sh
set -eu

alembic upgrade head

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec uvicorn app.main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}"
