"""エージェントどうしの連絡 (= あるタブの claude から、 別のタブの claude へ)。

タブの中の claude が `POST /agent-messages` を叩くと、 backend が本文に「誰から」 の封筒を付けて
宛先のタブへ届ける。 アカウントが違うタブどうしでも届く (= backend は全部のタブを知っている)。
受けるのは同じ機械の中からの呼び出しだけ。

人が打つ送信口 (= `/pty/{sid}/send`) とは別の口にしてある。 宛先の claude から見ると、 どちらも
端末に打たれた文として届くので、 区別は本文の 1 行目 (= `OPENING`) でしか付かない。 この口を通った
連絡には必ずその行が付き、 人の送信には付かない。

届ける前の検査は外へ任せる。 `config.json` の `agent_message_check` にコマンドを書くと、 連絡ごとに
それを走らせ、 終了コード 0 の時だけ届ける (= 0 以外は拒否して、 標準エラーの最後の行を理由として返す)。
書いていなければ検査なしで届ける。
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Request

from backend.errors import raise_error
from backend.state import sessions_meta
from backend.terminal.pty_discover import claude_in_pane
from backend.terminal.routes import pty_send
from backend.terminal.runner import jsonl_path_for_session

logger = logging.getLogger(__name__)
router = APIRouter()

# 連絡の 1 行目。 宛先の claude も、 端末の入力を読む外の道具も、 この行で「人が打った文ではない」
# と見分ける。 変えると見分けが外れるので固定 (= docs/reference/agent-messages.md に同じ行を載せている)。
OPENING = "Message from another session, relayed by the client (the operator did not type this):"
TAG = "agent-message"
# この口を叩けるのは同じ機械の中だけ (= タブの中の claude)。 "testclient" は starlette TestClient の host。
LOCAL_CLIENTS = ("127.0.0.1", "::1", "localhost", "testclient")
# 検査コマンドを待つ上限。 外の検査が自分で持つ上限より長く取る (= 先に切ると理由が失われる)。
CHECK_TIMEOUT_SEC = 200.0


def resolve_receiver(to: str) -> str:
    """宛先 (= タブの id か、 タブの名前) をタブの id にする。"""
    to = to.strip()
    if to in sessions_meta:
        return to
    named = [m.id for m in sessions_meta.values() if m.title == to]
    if len(named) == 1:
        return named[0]
    if not named:
        raise_error(404, "agent_message_unknown_receiver", f"宛先のタブが見つかりません: {to}", to=to)
    raise_error(409, "agent_message_ambiguous_receiver",
                f"同じ名前のタブが {len(named)} 個あります。 id で指定してください: {', '.join(named)}",
                to=to, ids=", ".join(named))
    raise AssertionError("unreachable")


def envelope(sender_id: str, text: str) -> str:
    """本文に「誰から」 を付ける。 本文の中の閉じタグは潰す (= 封筒の外へ文を足せない)。"""
    title = sessions_meta[sender_id].title.replace('"', "'").replace("\n", " ")
    body = text.strip().replace(f"</{TAG}", f"&lt;/{TAG}")
    return f'{OPENING}\n<{TAG} from="{title}" session="{sender_id}">\n{body}\n</{TAG}>'


def _write_private(text: str) -> Path:
    from backend.config import UPLOADS_TMP  # noqa: PLC0415
    UPLOADS_TMP.mkdir(parents=True, exist_ok=True)
    path = UPLOADS_TMP / f"agent-message-{uuid.uuid4().hex}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


async def check(receiver_id: str, text: str) -> None:
    """`agent_message_check` を走らせる。 通れば戻り、 拒否と実行不能は HTTP エラーにする。

    コマンドの語の中の `{file}` は本文を書いた file、 `{session}` は宛先の claude の session id
    (= その会話の記録 file の名前) に置き換わる。
    """
    from backend.config import AGENT_MESSAGE_CHECK  # noqa: PLC0415
    if not AGENT_MESSAGE_CHECK:
        return
    record = jsonl_path_for_session(receiver_id)
    if record is None:
        raise_error(409, "agent_message_receiver_not_ready",
                    "宛先の会話がまだ始まっていないため、 検査できません")
    path = _write_private(text)
    argv = [os.path.expanduser(word.replace("{file}", str(path)).replace("{session}", record.stem))
            for word in AGENT_MESSAGE_CHECK]
    try:
        done = await asyncio.to_thread(subprocess.run, argv, capture_output=True, text=True,
                                       timeout=CHECK_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        raise_error(503, "agent_message_check_failed", "連絡の検査が時間内に終わりませんでした")
    except OSError as error:
        logger.warning("agent message check could not run: %s", error)
        raise_error(503, "agent_message_check_failed", "連絡の検査を実行できませんでした")
    finally:
        path.unlink(missing_ok=True)
    if done.returncode != 0:
        reason = (done.stderr.strip().splitlines() or ["the check refused the message"])[-1]
        logger.info("agent message refused receiver=%s exit=%s", receiver_id, done.returncode)
        raise_error(403, "agent_message_refused", f"連絡は届けられませんでした: {reason}", reason=reason)


@router.post("/agent-messages")
async def post_agent_message(
    request: Request,
    to: str = Form(...),
    sender: str = Form(..., alias="from"),
    text: str = Form(...),
) -> dict:
    """タブの中の claude が、 別のタブの claude へ連絡を送る。

    form:
        to   (str): 宛先のタブの id、 またはタブの名前 (= 同じ名前が複数あれば id で)
        from (str): 送り主のタブの id (= そのタブの環境変数 `PWA_SID`)
        text (str): 本文
    """
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        logger.warning("agent message rejected: non-local client=%s", client_host)
        raise_error(403, "agent_message_local_only", "この口は同じ機械の中からだけ使えます")
    if sender not in sessions_meta:
        raise_error(400, "agent_message_unknown_sender", f"送り主のタブが見つかりません: {sender}", sender=sender)
    if not text.strip():
        raise_error(400, "agent_message_empty", "本文が空です")
    receiver_id = resolve_receiver(to)
    if receiver_id == sender:
        raise_error(400, "agent_message_to_self", "自分のタブへは送れません")
    # e2e (= CPC_E2E=1) には本物の claude が居ない。 送信口と同じく、 端末の代わりに記録へ行を足す。
    if os.environ.get("CPC_E2E") != "1" and not claude_in_pane(receiver_id):
        # 連絡で会話を起こさない: 新しい会話は最初の発話で起動の仕方が決まる。
        raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いていません")
    await check(receiver_id, text)
    result = await pty_send(receiver_id, {"text": envelope(sender, text), "enter": True}, None)
    logger.info("agent message sender=%s receiver=%s chars=%d ok=%s", sender, receiver_id, len(text), result.get("ok"))
    return {**result, "to": receiver_id}
