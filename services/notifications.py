"""Compatibility alias: tests and RQ job paths import services.notifications."""

from apex_receptionist.services import notifications as _real
import sys

sys.modules[__name__] = _real
