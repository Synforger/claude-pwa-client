"""The settings screen's endpoints.

- GET /settings : what the screen shows (usage and lines of the accounts, the tabs stopped by a line, the sleep and the
  rollover of each agent, the notification title, the child limit, the machine)
- PUT /settings : change some of the fields the screen may change (a partial update in the shape of `config.json`);
  the answer is what GET gives after the change

The fields, and what each may be set to, are in `backend/settings/settings_fields.py`. A field outside them is a 400.
"""
from __future__ import annotations

from fastapi import APIRouter, Body

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
