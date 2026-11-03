"""Production WSGI entry point.

Run with Gunicorn:  gunicorn -c gunicorn.conf.py wsgi:app

Importing this module does not start the in-process dev scheduler or the Flask
dev server (those only run under ``python app.py``).
"""

from app import app  # noqa: F401

__all__ = ["app"]
