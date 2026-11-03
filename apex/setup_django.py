"""Idempotent Django initialisation for Flask, CLI, and tests."""

from __future__ import annotations

import os


def setup_django() -> None:
    """Load Django so platform models can be used from the receptionist process."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apex.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()
