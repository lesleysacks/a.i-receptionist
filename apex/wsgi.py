"""Django WSGI entry for the Apex management platform."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apex.settings")

application = get_wsgi_application()
