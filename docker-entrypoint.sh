#!/usr/bin/env bash
set -euo pipefail

# Wait briefly for the database to accept connections (compose ordering safety).
python - <<'PY'
import os, time
from sqlalchemy import create_engine, text
url = os.getenv("DATABASE_URL", "sqlite:///receptionist.db")
if not url.startswith("sqlite"):
    engine = create_engine(url)
    for attempt in range(30):
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("Database did not become available in time")
PY

# Apply migrations (controlled, non-destructive). Never create_all in production.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Running database migrations (alembic upgrade head)..."
  alembic upgrade head
fi

exec "$@"
