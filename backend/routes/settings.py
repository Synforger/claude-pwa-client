"""The settings screen's endpoints.

- GET /settings : what the screen shows (usage and lines of the accounts, the tabs stopped by a line, the sleep and the
  rollover of each agent, the notification title, the child limit, the machine)
- PUT /settings : change some of the fields the screen may change (a partial update in the shape of `config.json`);
  the answer is what GET gives after the change
- PUT /settings/api-sources/{source} : change settings of a program that lists API tabs (`api_tab_sources`), in its
  own settings file, within the fields it declared; the answer is what GET gives after the change

The fields, and what each may be set to, are in `backend/settings/settings_fields.py`. A field outside them is a 400.
"""
from __future__ import annotations

from fastapi import APIRouter, Body

from backend import api_tabs
from backend._common.errors import raise_error
from backend.settings import Rejected, build_view, update_settings

router = APIRouter()


@router.get("/settings")
def get_settings() -> dict:
    return build_view()


@router.put("/settings")
def put_settings(update: dict = Body(...)) -> dict:
    try:
        update_settings(update)
    except Rejected as error:
        raise_error(400, "settings_rejected", "設定を変えられませんでした", reasons=error.reasons)
    except (OSError, ValueError) as error:
        raise_error(500, "settings_not_written", "設定の file を読めない、 または書けません", reason=str(error))
    return build_view()


@router.put("/settings/api-sources/{source}")
def put_api_source_settings(source: str, body: dict = Body(...)) -> dict:
    declared = api_tabs.current_table().source(source)
    if declared is None:
        raise_error(404, "api_source_unknown", "その名前の API のタブの元はありません", source=source)
    if declared.settings is None:
        raise_error(400, "settings_rejected", "設定を変えられませんでした",
                    reasons=[f"{source}: no settings file is declared"])
    fields = api_tabs.sources.settings_fields(source)
    try:
        api_tabs.write_values(declared.settings, fields, body.get("values"))
    except api_tabs.SettingsRejected as error:
        raise_error(400, "settings_rejected", "設定を変えられませんでした", reasons=error.reasons)
    except (OSError, ValueError) as error:
        raise_error(500, "settings_not_written", "設定の file を読めない、 または書けません", reason=str(error))
    return build_view()
