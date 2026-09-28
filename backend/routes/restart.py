"""backend の再起動 endpoint (= PWA の設定メニューから backend を立ち上げ直す)。

- GET  /backend/restartable : この backend を再起動できるか (= launchd の常駐 job として動いているか)
- POST /backend/restart     : launchd に `kickstart -k` を頼んで backend を立ち上げ直す

再起動は launchd に頼む (= 自分に SIGTERM を送らない)。 ターミナルで
`launchctl kickstart -k gui/<uid>/<label>` を打つのと同じ経路なので、 止まらない時の
強制終了も立ち上げ直しも launchd が持つ。 launchd の job でない backend (= 手で起動した
uvicorn) は止めたら戻らないので、 再起動できない扱いにしてボタンを出さない。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/backend")

# 応答を返し切ってから launchd に頼むための猶予 (= kickstart は即座にこのプロセスを止める)。
_RESTART_DELAY_SEC = 0.5


def launchd_label() -> str | None:
    """launchd の job として動いていればその label、 そうでなければ None。

    launchd は起動した job の環境に `XPC_SERVICE_NAME=<label>` を入れる。 ターミナルから
    起動したプロセスは `0`、 GUI アプリから起動したものは `application.<bundle id>...` を
    持つので、 どちらも job ではない。"""
    label = os.environ.get("XPC_SERVICE_NAME", "")
    if not label or label == "0" or label.startswith("application."):
        return None
    if shutil.which("launchctl") is None:
        return None
    return label


def _kickstart(label: str) -> None:
    # 新しい session で起動して、 kickstart が止める backend の process group から外す。
    subprocess.Popen(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@router.get("/restartable")
def restartable() -> dict:
    return {"restartable": launchd_label() is not None}


class RestartRequest(BaseModel):
    confirm: bool


@router.post("/restart", status_code=202)
async def restart(req: RestartRequest) -> dict:
    # 本文を JSON 必須にする (= FastAPI は Content-Type が JSON の要求しか本文として読まない)。
    # ブラウザは別サイトから JSON を送る前に preflight を挟むので、 開いただけのページが
    # 本文なし POST でこの backend を再起動させることはできない。
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    label = launchd_label()
    if label is None:
        raise HTTPException(
            status_code=409,
            detail="This backend is not running as a launchd job, so it would not come back after a restart.",
        )
    asyncio.get_running_loop().call_later(_RESTART_DELAY_SEC, _kickstart, label)
    return {"restarting": True}
