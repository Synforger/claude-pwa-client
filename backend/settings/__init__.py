"""The settings screen's backend: what it shows (`settings_view`) and the fields of `config.json` it may change
(`settings_fields`, `settings_store`; see `docs/reference/settings-screen.md`)."""
from backend.settings.settings_fields import Rejected
from backend.settings.settings_store import update_settings
from backend.settings.settings_view import build_view

__all__ = ["Rejected", "build_view", "update_settings"]
