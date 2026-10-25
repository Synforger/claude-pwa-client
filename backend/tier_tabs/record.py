"""Which tiers have had a tab, per agent: the record that keeps a closed tier tab closed. Called by `tier_tabs`.

The backend opens a tab for a tier only when the tier is not in this record yet (= a new folder). A tab the
operator closed stays closed: its tier stays in the record until `tabs open <tier>` opens it again. The file
is `TIER_TABS_PATH` (= `{"<agent_id>": ["normal", "projects/<P>", ...]}`); a missing or unreadable file is
an empty record.
"""

from __future__ import annotations

import json
import logging

from backend._common.paths import TIER_TABS_PATH
from backend._common.state import atomic_write_text

logger = logging.getLogger(__name__)


def load() -> dict[str, set[str]]:
    """The tiers each agent has had a tab for (= empty when the file is missing or unreadable)."""
    if not TIER_TABS_PATH.is_file():
        return {}
    try:
        data = json.loads(TIER_TABS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("tier_tabs.json could not be read, starting from an empty record", exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    return {agent: {tier for tier in tiers if isinstance(tier, str)}
            for agent, tiers in data.items() if isinstance(agent, str) and isinstance(tiers, list)}


def save(record: dict[str, set[str]]) -> None:
    """Write the record (= tiers sorted, so the file reads the same for the same record)."""
    TIER_TABS_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = {agent: sorted(tiers) for agent, tiers in sorted(record.items())}
    atomic_write_text(TIER_TABS_PATH, json.dumps(body, ensure_ascii=False, indent=2))
