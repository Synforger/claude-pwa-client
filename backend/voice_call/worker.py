"""電話の会話 1 本を、 backend 本体と別の process で動かす (= 音の送り出しを、 backend の他の仕事で止めない)。

backend の `routes/voice_call.py` が通話ごとに起こす。 標準入出力で 1 行に 1 つの JSON をやり取りする:

    入   {"type": "start", "base_url": …, "session_id": …, "client": …, "marks": […], "conversation": {…}, "turn": …}
    入   {"type": "offer", "sdp": …, "type_": "offer", …}      → 出 {"type": "answer", "answer": {…}}
                                                               → 出 {"type": "error", "message": …}
    入   {"type": "patch", "pc_id": …, "candidates": […]}

会話が終わるか、 backend が標準入力を閉じたら終わる。 log は `logs/voice-call.log` に出す (= backend の log と同じく
5 MB で回して 3 世代まで。 Pipecat 自身の log は WARNING 以上だけ)。 起動に失敗した時の traceback だけは標準エラー
(= backend の起動の log) に出る。
"""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import sys

from loguru import logger as pipecat_logger

from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from backend.paths import LOGS_DIR
from backend.voice_call.client import BackendClient
from backend.voice_call.pipeline import run_call

logger = logging.getLogger("backend.voice_call.worker")

LOG_PATH = LOGS_DIR / "voice-call.log"
LOG_MAX_BYTES = 5 * 1024 * 1024   # backend の log と同じ (= backend/main.py)
LOG_BACKUP_COUNT = 3
PIPECAT_LOG_LEVEL = "WARNING"     # Pipecat の DEBUG / INFO は通話 1 回で数十 KB になる


def setup_logging() -> None:
    """この process の log を、 回る専用の file に出す。 Pipecat の log (= loguru) も同じ file へ流す。"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        str(LOG_PATH), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(process)d %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def to_logging(message) -> None:
        record = message.record
        logging.getLogger(f"pipecat.{record['name']}").log(record["level"].no, record["message"])

    pipecat_logger.remove()
    pipecat_logger.add(to_logging, level=PIPECAT_LOG_LEVEL, format="{message}")


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


async def _lines() -> asyncio.StreamReader:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=1 << 20)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    return reader


async def main() -> None:
    reader = await _lines()
    start = json.loads(await reader.readline())
    handler = SmallWebRTCRequestHandler()
    call: asyncio.Task | None = None

    async with BackendClient(start["base_url"], start["session_id"], start["client"]) as backend:
        async def connected(connection) -> None:
            nonlocal call
            call = asyncio.create_task(run_call(connection, backend, start))

        async def read_requests() -> None:
            while line := await reader.readline():
                message = json.loads(line)
                kind = message.pop("type")
                try:
                    if kind == "offer":
                        message["type"] = message.pop("type_", "offer")
                        answer = await handler.handle_web_request(
                            request=SmallWebRTCRequest.from_dict(message), webrtc_connection_callback=connected)
                        _write({"type": "answer", "answer": answer})
                    elif kind == "patch":
                        await handler.handle_patch_request(SmallWebRTCPatchRequest(
                            pc_id=message["pc_id"],
                            candidates=[IceCandidate(**c) for c in message.get("candidates") or []]))
                except Exception as error:  # noqa: BLE001 (= 申し込みの失敗は backend へ返して、 process は終える)
                    logger.warning("voice call: %s failed: %s", kind, error)
                    _write({"type": "error", "message": str(error)})
                    return

        requests = asyncio.create_task(read_requests())
        while call is None and not requests.done():
            await asyncio.sleep(0.05)
        if call is not None:
            await asyncio.wait({call, requests}, return_when=asyncio.FIRST_COMPLETED)
            if not call.done():
                call.cancel()
        requests.cancel()
        await handler.close()


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
