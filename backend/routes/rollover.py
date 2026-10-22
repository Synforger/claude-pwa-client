"""自動の入れ替え (= 会話を締めて、 同じタブで新しい会話を起動し直す) の発話と、 起動し直す口。

会話が長くなると context が埋まる。 入れ替えは、 今の会話に「区切りで締めて、 次の会話へ引き継いで」 と
頼み、 締め終えた会話が頼んできたら、 そのタブの claude を終了して新しい会話を起動する。 流れ:

    1. backend の見張り (= `backend/rollover.py`) が、 条件の立ったタブへ締めを頼む発話を打つ
    2. そのタブの claude が、 次の会話に要る物を書き残して `POST /sessions/{sid}/rollover` を叩く
    3. backend がそのタブを終了して作り直し、 渡された本文を最初の発話として新しい会話を起動する

1 と 3 の発話は端末から入るので、 記録では人が打った発話と同じ行になる。 どちらも 1 行目が固定の文
(= `OPENING`) で始まり、 人の送信には付かない。 宛先の claude も、 端末の入力を読む外の道具も、 その行で
「人が打った文ではない」 と見分ける。

3 の本文は、 前の会話から次の会話への連絡に当たる。 次の会話は同じタブで、 同じ起動の仕方で立つ今の会話の
続きなので、 届ける前の検査 (= `agent_message_check`) は宛先を今の会話として通す (= 今の会話が読んだ境界の
名前と中身は通り、 読んでいない境界の物は止まる)。 今の会話が止められた時は、 同じタブの前の会話を新しい順に
宛先にして通し直す (= 起動に失敗した会話は境界をまだ読んでいないので、 タブの階層の path を名乗れない。
タブが居る境界は、 そのタブの前の会話が読んだ所)。 どれも止めたら、 今の会話の理由で断る。 記録が 1 つも
見つからない時だけ、 「どの会話でもない宛先」 の名前で通す (= 何も読んでいない相手。 別の機械への連絡と同じ扱い)。

口は 202 を返してから終了に入る。 叩いた道具は終了されるタブの中で動いていて、 終了と一緒に落ちる。
"""
from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Form, HTTPException, Request

from backend.core.jsonl_predicates import ROLLOVER_OPENING as OPENING
from backend.errors import raise_error
from backend.jsonl import history as session_history
from backend.routes.agent_messages import LOCAL_CLIENTS, judge
from backend.state import sessions_meta
from backend.terminal.routes import pty_send
from backend.terminal.runner import jsonl_path_for_session

logger = logging.getLogger(__name__)
router = APIRouter()

TAG = "session-rollover"
# 封筒のタグと同じ形の文字列を、 本文の側から書けなくする (= 本文で封筒を閉じる / 別の封筒を装う)。
_TAG_LIKE = re.compile(rf"<(/?)({TAG}|agent-message|operator-said)")
# 202 が呼び手に届いてから、 そのタブを終了するまでの間。
ROLL_DELAY_SEC = 1.0
# 走っている入れ替えの task (= 参照を持たないと、 終わる前に回収されることがある)。
_rolling: set[asyncio.Task] = set()


def _plain(text: str) -> str:
    return _TAG_LIKE.sub(r"&lt;\1\2", text.strip())


def close_envelope(session_id: str, reason: str, context_pct: int, idle_minutes: int) -> str:
    """締めを頼む発話。 reason は `context` (= 作業中に割合が閾値へ届いた) か `idle` (= 割合が閾値を超えた
    まま静かになった)。 本文は、 この仕組みを知らない claude が読んでも次の動きが分かる 1 段落。"""
    why = (f"Context is at {context_pct}%." if reason == "context" else
           f"Context is at {context_pct}% and this session has been quiet for {idle_minutes} minutes.")
    return (
        f'{OPENING}\n<{TAG} phase="close" reason="{reason}" context_pct="{context_pct}" '
        f'idle_minutes="{idle_minutes}">\n'
        f"{why} Wrap up at the next stopping point and hand over: write down what the next session needs, "
        f"then ask the client to start it (POST /sessions/{session_id}/rollover, form field `text` = what "
        f"the next session opens with).\n"
        f"</{TAG}>"
    )


def start_envelope(text: str) -> str:
    """起動し直した会話の最初の発話。 本文は前の会話が渡した物。"""
    return f'{OPENING}\n<{TAG} phase="start">\n{_plain(text)}\n</{TAG}>'


async def _roll(session_id: str, first: str) -> None:
    """そのタブを終了して作り直し、 first を最初の発話として新しい会話を起動する。"""
    # routes/sessions は読み込まれた時点の agent の設定を掴む。 この module を読むだけの側 (= 見張り) まで
    # それに巻き込まないよう、 終了を呼ぶ時に読む。
    from backend.routes.sessions import restart_session  # noqa: PLC0415
    await asyncio.sleep(ROLL_DELAY_SEC)
    try:
        out = await restart_session(session_id, session_id)
        if not out.get("ok"):
            # タブは shell のまま残る。 次に人が送った発話が、 最初の発話として会話を起動する。
            logger.warning("rollover: restart failed session=%s reason=%s", session_id, out.get("reason"))
            return
        result = await pty_send(session_id, {"text": first, "enter": True}, None)
        logger.info("rollover: session=%s started=%s", session_id, result.get("ok"))
    except Exception:
        logger.exception("rollover failed session=%s", session_id)


def _tab_records(session_id: str) -> list[str]:
    """そのタブの会話の記録の名前を、 今の会話から古い方へ (= 在処を控えていない会話は除く)。"""
    record = jsonl_path_for_session(session_id)
    names = [record.stem] if record is not None else []
    for path, _ in reversed(session_history.ended(session_id)):
        if path is not None and path.stem not in names:
            names.append(path.stem)
    return names


async def _judge_as_the_tab(session_id: str, text: str) -> None:
    """次の会話へ渡す本文を、 そのタブの会話を宛先として検査する。 1 つが通せば通り、 全部が止めたら最初
    (= 今の会話) の理由で断る。 検査が走らなかった時は、 その場で断る。

    次の会話は今の会話の続き (= 同じタブ・同じ階層で立ち、 同じ境界を読む)。 階層の path は境界の folder の
    名前を含むので、 何も読んでいない相手として通すと、 境界の中の階層は起動し直せない。"""
    first_refusal: HTTPException | None = None
    for name in _tab_records(session_id) or [f"rollover:{session_id}"]:
        try:
            await judge(name, text, session_id)
            return
        except HTTPException as refused:
            if refused.status_code != 403:
                raise
            first_refusal = first_refusal or refused
    raise first_refusal


@router.post("/sessions/{session_id}/rollover", status_code=202)
async def post_rollover(request: Request, session_id: str, text: str = Form(...)) -> dict:
    """タブの中の claude が、 自分の会話を終了して新しい会話を起動し直すよう頼む。

    form:
        text (str): 新しい会話の最初の発話に入れる本文 (= 次の会話が何から始めるか)
    """
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        logger.warning("rollover rejected: non-local client=%s", client_host)
        raise_error(403, "rollover_local_only", "この口は同じ機械の中からだけ使えます")
    if session_id not in sessions_meta:
        raise_error(404, "rollover_unknown_session", f"タブが見つかりません: {session_id}", session=session_id)
    if not text.strip():
        raise_error(400, "rollover_empty", "本文が空です")
    from backend.config import AGENT_MESSAGE_CHECK  # noqa: PLC0415
    if AGENT_MESSAGE_CHECK:
        await _judge_as_the_tab(session_id, text)
    task = asyncio.create_task(_roll(session_id, start_envelope(text)))
    _rolling.add(task)
    task.add_done_callback(_rolling.discard)
    logger.info("rollover accepted session=%s chars=%d", session_id, len(text))
    return {"rolling": True}
