"""iPhone の app との中継 (= 頼みを渡し、 答えを待つ)。

app は起きている間 `/device/ws` につなぎ、 最初に自分のできる操作の一覧を送る (= hello)。 Mac の命令
(= `cpc device`) は `/device/ops` に頼みを出し、 中継は番号を振って app へ渡し、 同じ番号の答えを待つ。

    app → backend   {"type": "hello", "device": 名前, "app": 版, "catalog": [操作, ...]}
                    {"type": "result", "id": 番号, "ok": true, "result": 値, "files": [{"name", "mime", "data"}]}
                    {"type": "result", "id": 番号, "ok": false, "error": 理由}
    backend → app   {"type": "call", "id": 番号, "op": "<種類>.<操作>", "args": {...}}

操作 1 つの形 (= app が持つ真値): {"name", "kind": read | add | change | delete | act, "summary",
"params": [{"name", "type", "required", "description"}], "timeout_s", "foreground"}。 写真のような大きい答えは
`files` に base64 で載り、 中継が file に書いて、 答えには path を返す。

つなぐ app は 1 台 (= 後からつないだ方に替わる)。 一覧は file に控え、 app が居ない時の説明に使う。
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# 操作が時間を名乗らない時に、 答えを待つ長さ
DEFAULT_TIMEOUT_S = 30.0
# file の名前に使ってよい文字 (= app が付けた名前から、 それ以外は落とす)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class DeviceOffline(Exception):
    """app がつながっていない (= 通話中でも、 前に出してもいない)。"""


class UnknownOp(Exception):
    """app の一覧に無い操作。"""


class DeviceTimeout(Exception):
    """時間内に答えが来なかった。"""


class DeviceFailed(Exception):
    """app が、 できなかったと答えた。"""


Send = Callable[[dict], Awaitable[None]]


@dataclass
class _Link:
    send: Send
    device: str
    app: str
    catalog: list[dict]
    since: float = field(default_factory=time.time)


class DeviceHub:
    """つながっている app 1 台と、 答えを待っている頼み。"""

    def __init__(self, catalog_path: Path, files_dir: Path):
        self._catalog_path = catalog_path
        self._files_dir = files_dir
        self._link: _Link | None = None
        self._waiting: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)

    # --- app の側 ---------------------------------------------------------------------------------------------

    def attach(self, send: Send, hello: dict) -> _Link:
        """app がつないだ (= 前の app は外す)。 一覧を控える。"""
        if self._link is not None:
            self._fail_waiting("another app connected")
        catalog = [op for op in hello.get("catalog") or [] if isinstance(op, dict) and op.get("name")]
        self._link = _Link(send=send, device=str(hello.get("device") or "?"), app=str(hello.get("app") or "?"),
                           catalog=catalog)
        self._save_catalog()
        logger.info("device: %s (app %s) connected with %d operations", self._link.device, self._link.app,
                    len(catalog))
        return self._link

    def detach(self, link: _Link) -> None:
        """app が切れた (= 後からつないだ app に替わった時は、 何もしない)。"""
        if self._link is not link:
            return
        self._link = None
        self._fail_waiting("the app disconnected")
        logger.info("device: %s disconnected", link.device)

    def receive(self, message: dict) -> None:
        """app からの答え。"""
        if message.get("type") != "result":
            return
        waiting = self._waiting.pop(str(message.get("id")), None)
        if waiting is None or waiting.done():
            return
        if message.get("ok"):
            result = message.get("result")
            saved = self._save_files(message.get("files") or [])
            if saved:
                result = {"value": result, "files": saved} if not isinstance(result, dict) else {**result, "files": saved}
            waiting.set_result(result)
        else:
            waiting.set_exception(DeviceFailed(str(message.get("error") or "failed")))

    # --- Mac の側 ---------------------------------------------------------------------------------------------

    async def call(self, op: str, args: dict, timeout_s: float | None = None):
        """app に操作を 1 つ頼み、 答えを返す。"""
        link = self._link
        if link is None:
            raise DeviceOffline("the iPhone app is not connected (it connects while a call is on or while it is open)")
        spec = next((o for o in link.catalog if o.get("name") == op), None)
        if spec is None:
            raise UnknownOp(op)
        wait = timeout_s or float(spec.get("timeout_s") or DEFAULT_TIMEOUT_S)
        call_id = str(next(self._ids))
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiting[call_id] = future
        started = time.monotonic()
        try:
            await link.send({"type": "call", "id": call_id, "op": op, "args": args})
            return await asyncio.wait_for(future, wait)
        except asyncio.TimeoutError as error:
            raise DeviceTimeout(f"{op} did not answer within {wait:.0f} s") from error
        finally:
            self._waiting.pop(call_id, None)
            logger.info("device: %s answered in %.1f s", op, time.monotonic() - started)

    def status(self) -> dict:
        """つながっているかと、 できる操作の一覧 (= 居ない時は最後に控えた一覧)。"""
        link = self._link
        if link is not None:
            return {"connected": True, "device": link.device, "app": link.app, "since": link.since,
                    "catalog": link.catalog}
        saved = self._load_catalog()
        return {"connected": False, **saved}

    # --- 内側 -------------------------------------------------------------------------------------------------

    def _fail_waiting(self, reason: str) -> None:
        for waiting in self._waiting.values():
            if not waiting.done():
                waiting.set_exception(DeviceOffline(reason))
        self._waiting.clear()

    def _save_catalog(self) -> None:
        link = self._link
        if link is None:
            return
        self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._catalog_path.write_text(json.dumps(
            {"device": link.device, "app": link.app, "since": link.since, "catalog": link.catalog},
            ensure_ascii=False, indent=1))

    def _load_catalog(self) -> dict:
        try:
            saved = json.loads(self._catalog_path.read_text())
        except (OSError, ValueError):
            return {"catalog": []}
        return saved if isinstance(saved, dict) else {"catalog": []}

    def _save_files(self, files: list) -> list[str]:
        saved = []
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for index, item in enumerate(files):
            if not isinstance(item, dict) or not isinstance(item.get("data"), str):
                continue
            name = _SAFE_NAME.sub("-", str(item.get("name") or f"file-{index}")).strip("-.") or f"file-{index}"
            self._files_dir.mkdir(parents=True, exist_ok=True)
            path = self._files_dir / f"{stamp}-{index}-{name}"
            path.write_bytes(base64.b64decode(item["data"]))
            saved.append(str(path))
        return saved
