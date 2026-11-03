"""Django ASGI entry (unused in Phase 1; Gunicorn still serves Flask + this app)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apex.settings")

application = get_asgi_application()
