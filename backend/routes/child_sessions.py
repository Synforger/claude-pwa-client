"""子のタブ (= あるタブの claude が、 仕事を渡すために立てる別のタブ)。

タブの中の claude が `POST /sessions/{sid}/children` を叩くと、 backend が新しいタブを立て、 渡された本文を
そのタブの最初の発話として、 叩いたタブ (= 親) からの連絡の封筒に入れて届ける。 子のタブは自分の会話を持つ
ので、 親の会話が終わっても (= 自動の入れ替えで起動し直しても) 回り続ける。 親子の関係はタブの記録が持つ
(= `parent_id` と `child`)。 タブの id は入れ替えでも変わらないので、 子は親のタブの id 宛てに連絡を返せば、
親の今の会話に届く。 子は親と同じ階層で、 親の仕事の続きを受け持つ (= 階層を決めるのは起動する側)。

最初の発話は、 同じ機械の別のタブからの連絡と同じ封筒にする (= 1 行目は `AGENT_MESSAGE_OPENING`)。 子の
claude も、 端末の入力を読む外の道具も、 「人が打った文ではない」 を連絡と同じ 1 行目で見分ける。 届ける前の
検査 (= `agent_message_check`) は、 自動の入れ替えと同じに宛先を親の今の会話として通す (= 子は親の仕事の
続きで、 親が読んだ境界の名前と中身は通り、 読んでいない境界の物は止まる)。 親の会話の記録が見つからない時
だけ、 「どの会話でもない宛先」 の名前で通す (= 何も読んでいない相手)。 検査が通るまでタブは立てない
(= 断られた本文で空のタブを残さない)。

1 つのタブが同時に持てる子の数は `child_sessions_max` が決める (= 既定 5)。 閉じるのは今までのタブと同じ
`DELETE /sessions/{sid}` で、 閉じた子は数から外れる。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request

from backend.errors import raise_error
from backend.routes.agent_messages import LOCAL_CLIENTS, envelope, judge
from backend.state import register_session, sessions_meta
from backend.terminal.routes import pty_send
from backend.terminal.runner import jsonl_path_for_session
from backend.terminal.session_resolver import ensure_pty_session_for

logger = logging.getLogger(__name__)
router = APIRouter()


def children_of(parent_id: str) -> list[str]:
    """そのタブの子のタブの id (= 立てた順)。 フォークのタブは数えない。"""
    return [m.id for m in sessions_meta.values() if m.child and m.parent_id == parent_id]


@router.post("/sessions/{session_id}/children")
async def post_child_session(
    request: Request,
    session_id: str,
    agent_id: str = Form(...),
    text: str = Form(...),
    title: str | None = Form(None),
) -> dict:
    """タブの中の claude が、 子のタブを立てて最初の発話を渡す。 → 立てたタブの記録 (= `GET /sessions` の 1 件)。

    form:
        agent_id (str): 子のタブの agent (= `config.json` の `agents` の key)
        text     (str): 子のタブの最初の発話に入れる本文 (= 渡す仕事)
        title    (str): 子のタブの名前 (= 省くと agent の既定の名前)

    子のタブは親と同じ口座で動く。
    """
    from backend.config import AGENT_MESSAGE_CHECK, AGENTS, CHILD_SESSIONS_MAX  # noqa: PLC0415
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        logger.warning("child session rejected: non-local client=%s", client_host)
        raise_error(403, "child_session_local_only", "この口は同じ機械の中からだけ使えます")
    parent = sessions_meta.get(session_id)
    if parent is None:
        raise_error(404, "child_session_unknown_parent", f"親のタブが見つかりません: {session_id}", session=session_id)
    if agent_id not in AGENTS:
        raise_error(400, "invalid_agent_id", "agent_id が無効です")
    if not text.strip():
        raise_error(400, "child_session_empty", "本文が空です")
    held = children_of(session_id)
    if len(held) >= CHILD_SESSIONS_MAX:
        raise_error(409, "child_session_limit",
                    f"このタブの子は {len(held)} 個で、 上限 ({CHILD_SESSIONS_MAX}) に届いています。 終わった子を閉じてから立ててください",
                    limit=CHILD_SESSIONS_MAX, children=", ".join(held))
    if AGENT_MESSAGE_CHECK:
        # 子は親の仕事の続き (= 同じ階層で立ち、 同じ境界を読む)。 宛先は親の今の会話にする。 記録が無い時だけ、
        # この機械のどの会話でもない名前 (= 何も読んでいない相手) で通す。
        record = jsonl_path_for_session(session_id)
        name = record.stem if record is not None else f"child:{session_id}"
        await judge(name, text, session_id)
    meta = register_session(agent_id, (title or "").strip() or None, parent_id=session_id,
                            account_id=parent.account_id, child=True)
    try:
        await ensure_pty_session_for(meta.id)
    except Exception:
        logger.exception("child session spawn failed for %s", meta.id)
    # 子は親が立てたので、 封筒には親のタブ名をそのまま出す (= 送り主の名前を伏せる検査は、 相手を知らない
    # 連絡のための物)。
    result = await pty_send(meta.id, {"text": envelope(session_id, text), "enter": True}, None)
    logger.info("child session parent=%s child=%s agent=%s chars=%d started=%s",
                session_id, meta.id, agent_id, len(text), result.get("ok"))
    return {**meta.to_dict(), "started": bool(result.get("ok"))}
