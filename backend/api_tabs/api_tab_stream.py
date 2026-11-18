"""Follows the record files of the API tabs and the spend files of the wallets, and tells the screens what changed.

Every half second (`POLL_INTERVAL_SEC`) it looks at each record: rows appended since the last look go to the
subscribers as the same events a Claude tab's rows become, with the tab's id in them. It also keeps what the doors read
instead of reading files themselves: the context amount of each tab (computed from the rows it reads) and the reading of
each wallet's spend file; when one of them changes, the overview is announced again.

Where it starts: at the backend's start a record is followed from the end of its whole rows (a restart does not stream
the whole conversation again); a record that appears later is followed from 0; a record that got shorter, or vanished,
is followed from 0 again and a `history_refetch` is sent, so that the screen fetches the history again.
Runs as one task of the backend (`api_tab_stream_loop`). Read by `api_tab_rows.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from backend._common.state import jsonl_event_broadcaster, sessions_overview
from backend.api_tabs.api_spend import Spend, file_signature, read_spend_file, this_months
from backend.api_tabs.api_tab_record import Changes, line_number_at, look_at_record
from backend.api_tabs.api_tab_table import ApiAccount, ApiTab, ApiTabTable, current_table
from backend.api_tabs.context_tokens import context_tokens_of_row
from backend.api_tabs.log_throttle import LogThrottle
from backend.jsonl.events import jsonl_line_to_events
from backend.observability.correlation import current_corr_id

logger = logging.getLogger(__name__)

#: How often the files are looked at (= the same as the Claude tabs' record watch, `jsonl/routes.py POLL_INTERVAL`).
POLL_INTERVAL_SEC = 0.5
#: A broken row is written to the log once a minute per reason, an unreadable spend file once an hour per reason.
ROW_LOG_INTERVAL_SEC = 60.0
SPEND_LOG_INTERVAL_SEC = 3600.0


def _look_at_spend(wallet: ApiAccount) -> tuple[Spend | None, str | None]:
    """The reading of a wallet's spend file and why there is none, as (spend, reason). Blocking."""
    assert wallet.spend is not None
    try:
        return read_spend_file(wallet.spend), None
    except FileNotFoundError:
        return None, "file not found"
    except (OSError, ValueError) as error:
        return None, str(error)


def _look_at_everything(
    tabs: list[tuple[ApiTab, int | None, bool]],
    wallets: list[tuple[ApiAccount, object]],
) -> tuple[list[tuple[ApiTab, Changes]], list[tuple[ApiAccount, tuple[int, int] | None, Spend | None, str | None]]]:
    """One blocking look at every record and every spend file whose signature changed (done in a worker thread)."""
    changes = [(tab, look_at_record(tab.record, offset, present)) for tab, offset, present in tabs]
    spends = []
    for wallet, previous in wallets:
        assert wallet.spend is not None
        signature = file_signature(wallet.spend)
        if previous is not None and previous == (signature,):
            continue
        spend, reason = _look_at_spend(wallet)
        spends.append((wallet, signature, spend, reason))
    return changes, spends


class ApiTabStream:
    """What the stream knows of each API tab and wallet since the backend started."""

    def __init__(self) -> None:
        self._offsets: dict[str, int | None] = {}
        self._present: dict[str, bool] = {}
        self._tokens: dict[str, int | None] = {}
        self._spend_signatures: dict[str, tuple[int, int] | None] = {}
        self._spends: dict[str, Spend | None] = {}
        self._spend_reasons: dict[str, str | None] = {}
        self._table: ApiTabTable | None = None
        self._row_log = LogThrottle(ROW_LOG_INTERVAL_SEC)
        self._spend_log = LogThrottle(SPEND_LOG_INTERVAL_SEC)

    def context_tokens(self, tab_id: str) -> int | None:
        """The context amount of the tab's last answer (None until a row with a `usage` was read)."""
        return self._tokens.get(tab_id)

    def spend(self, account: str, now: datetime) -> Spend | None:
        """This month's spend of the wallet `account` (None when the file says none, or another month)."""
        return this_months(self._spends.get(account), now)

    async def poll(self) -> None:
        """Look at every record and spend file once, and publish what is new."""
        table = current_table()
        if table is not self._table:
            self._forget_removed(table)
            self._table = table
            sessions_overview.notify()
        tabs = [(tab, self._offsets.get(tab.id), self._present.get(tab.id, False)) for tab in table.tabs]
        wallets = [(wallet, self._spend_signatures_of(wallet)) for wallet in table.accounts if wallet.spend is not None]
        if not tabs and not wallets:
            return                                                      # nothing declared: no thread is woken every half second
        changes, spends = await asyncio.to_thread(_look_at_everything, tabs, wallets)
        changed = False
        for tab, found in changes:
            changed = self._apply_tab(tab, found) or changed
        for wallet, signature, spend, reason in spends:
            changed = self._apply_spend(wallet, signature, spend, reason) or changed
        self._log_unreadable_spends(table)
        if changed:
            sessions_overview.notify()

    async def run(self) -> None:
        """Poll until cancelled. A failed pass is written to the log (once a minute per reason) and the next one runs."""
        while True:
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 (= the loop must outlive any one bad pass)
                if self._row_log.allows("poll", repr(error)):
                    logger.exception("api tab: a pass of the stream failed")
            await asyncio.sleep(POLL_INTERVAL_SEC)

    def _spend_signatures_of(self, wallet: ApiAccount) -> object:
        """What was seen of the wallet's file last time as `(signature,)`, None before the first look."""
        if wallet.name not in self._spend_signatures:
            return None
        return (self._spend_signatures[wallet.name],)

    def _forget_removed(self, table: ApiTabTable) -> None:
        """Drop what is kept for tabs and wallets the configuration no longer declares."""
        for sid in [sid for sid in self._offsets if table.tab(sid) is None]:
            for kept in (self._offsets, self._present, self._tokens):
                kept.pop(sid, None)
        for name in [name for name in self._spend_signatures if table.account(name) is None]:
            for kept in (self._spend_signatures, self._spends, self._spend_reasons):
                kept.pop(name, None)

    def _apply_tab(self, tab: ApiTab, found: Changes) -> bool:
        """Take one look at a record: publish its new rows and keep the position. True when the context amount changed."""
        sid = tab.id
        previous = self._tokens.get(sid)
        self._offsets[sid] = found.offset
        self._present[sid] = found.present
        if found.unreadable is not None and self._row_log.allows(sid, found.unreadable):
            logger.warning("api tab: %s line 0 skipped: record unreadable: %s", sid, found.unreadable)
        if found.rewound:
            jsonl_event_broadcaster.publish(sid, {"type": "history_refetch", "sid": sid, "corr_id": current_corr_id()})
        tokens = found.scanned_tokens if found.scanned else previous
        for raw, end in found.rows:
            tokens = self._publish_row(tab, raw, end, tokens)
        self._tokens[sid] = tokens
        return tokens != previous

    def _publish_row(self, tab: ApiTab, raw: str, end: int, tokens: int | None) -> int | None:
        """Turn one row into events and publish them. → the context amount after the row."""
        try:
            row = json.loads(raw)
        except ValueError as error:
            self._log_skipped_row(tab, end, f"not JSON: {error}")
            return tokens
        amount = context_tokens_of_row(row)
        for event in jsonl_line_to_events(row, None):
            event.setdefault("sid", tab.id)
            jsonl_event_broadcaster.publish(tab.id, event, end)
        return tokens if amount is None else amount

    def _log_skipped_row(self, tab: ApiTab, end: int, reason: str) -> None:
        if not self._row_log.allows(tab.id, reason):
            return
        try:
            number = line_number_at(tab.record, end)
        except OSError:
            number = 0
        logger.warning("api tab: %s line %d skipped: %s", tab.id, number, reason)

    def _apply_spend(self, wallet: ApiAccount, signature: tuple[int, int] | None, spend: Spend | None,
                     reason: str | None) -> bool:
        """Keep one new look at a wallet's spend file. True when the figure the screens show changed."""
        previous = self._spends.get(wallet.name)
        self._spend_signatures[wallet.name] = signature
        self._spends[wallet.name] = spend
        self._spend_reasons[wallet.name] = reason
        return spend != previous

    def _log_unreadable_spends(self, table: ApiTabTable) -> None:
        for wallet in table.accounts:
            reason = self._spend_reasons.get(wallet.name)
            if reason is None:
                self._spend_log.forget(wallet.name)
            elif self._spend_log.allows(wallet.name, reason):
                logger.warning("api account: %s spend unreadable: %s", wallet.name, reason)


#: The one stream of the backend process; the rows read what it keeps.
stream = ApiTabStream()


async def api_tab_stream_loop() -> None:
    """The backend's task that follows the API tabs' files (started in the lifespan, cancelled when it ends)."""
    await stream.run()
