"""The endpoint that answers how much this machine holds now and how much room is left (= `tabs capacity`).

An agent that hands work to child tabs reads it before starting them: the child limit of the settings (none unless the
operator wrote one), the tabs and the claudes that run, the memory each claude takes and the machine's memory, and each
account's usage. Plain numbers only (`backend/capacity/capacity_view.py`).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from backend._common import config
from backend._common.local_door import require_this_machine
from backend.capacity import capacity_sensors
from backend.capacity.capacity_view import build_view

router = APIRouter()


@router.get("/capacity")
async def get_capacity(request: Request, session: str | None = Query(None)) -> dict:
    """How much this machine holds now (`backend/capacity/capacity_view.py`).

    query:
        session (str, optional): the tab that asks, whose child tabs are counted in `children_of_caller`
    """
    require_this_machine(request, "capacity_local_only")
    tabs, memory, usage = await asyncio.gather(asyncio.to_thread(capacity_sensors.read_tabs),
                                               asyncio.to_thread(capacity_sensors.read_memory_now),
                                               asyncio.to_thread(capacity_sensors.read_usage))
    return build_view(machine=config.MACHINE_NAME, child_sessions_max=config.CHILD_SESSIONS_MAX, caller=session,
                      tabs=tabs, memory=memory, usage=usage)
