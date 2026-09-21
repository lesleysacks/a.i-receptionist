"""Gunicorn production configuration (env-tunable)."""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "30"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")
# Logs go to stdout/stderr for container-friendly, structured logging.
accesslog = "-"
errorlog = "-"
