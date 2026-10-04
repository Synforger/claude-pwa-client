"""エージェントどうしの連絡 (= あるタブの claude から、 別のタブの claude へ)。

タブの中の claude が `POST /agent-messages` を叩くと、 backend が本文に「誰から」 の封筒を付けて
宛先のタブへ届ける。 アカウントが違うタブどうしでも届く (= backend は全部のタブを知っている)。
受けるのは同じ機械の中からの呼び出しだけ。

人が打つ送信口 (= `/pty/{sid}/send`) とは別の口にしてある。 宛先の claude から見ると、 どちらも
端末に打たれた文として届くので、 区別は本文の 1 行目 (= `OPENING`) でしか付かない。 この口を通った
連絡には必ずその行が付き、 人の送信には付かない。

送り主のタブで人が最後に打った発話が在れば、 それも封筒に入れて届ける (= `<operator-said>`)。 宛先の
claude は、 連絡が人の指示から出た物かを、 送り主の言い分ではなく人の言葉そのもので判断できる。
送り主の今の作業が別のタブからの連絡で始まっていた時は付けない。

届ける前の検査は外へ任せる。 `config.json` の `agent_message_check` にコマンドを書くと、 連絡ごとに
それを走らせ、 終了コード 0 の時だけ届ける (= 0 以外は拒否して、 標準エラーの最後の行を理由として返す)。
書いていなければ検査なしで届ける。 人の発話を付けてよいかは `agent_message_operator_check` が別に決める
(= 0 以外なら発話を付けずに本文だけ届ける)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Request

from backend.core.jsonl_predicates import is_user_prompt, unwrap_pasted
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
# 送り主のタブで人が最後に打った発話を入れる場所。 backend だけが書く。
OPERATOR_TAG = "operator-said"
# 封筒のタグと同じ形の文字列を、 中身の側から書けなくする (= 本文で封筒を閉じる / 人の発話を装う)。
_TAG_LIKE = re.compile(rf"<(/?)({TAG}|{OPERATOR_TAG})")
# 記録を末尾から読む時の 1 回分。 1 行がこれより長くても読める (= 足りなければ前へ継ぎ足す)。
_TAIL_CHUNK = 256 * 1024
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


def _plain(text: str) -> str:
    return _TAG_LIKE.sub(r"&lt;\1\2", text.strip())


def envelope(sender_id: str, text: str, operator_said: str | None = None) -> str:
    """本文に「誰から」 を付ける。 中身の側の、 封筒のタグと同じ形の文字列は潰す (= 本文から封筒を
    閉じて外へ文を足すことも、 人の発話を装うことも出来ない)。"""
    title = sessions_meta[sender_id].title.replace('"', "'").replace("\n", " ")
    said = f"<{OPERATOR_TAG}>\n{_plain(operator_said)}\n</{OPERATOR_TAG}>\n" if operator_said else ""
    return f'{OPENING}\n<{TAG} from="{title}" session="{sender_id}">\n{said}{_plain(text)}\n</{TAG}>'


def _lines_from_the_end(path: Path):
    """記録の行を新しい順に返す。 file を丸ごと読まない (= 記録は 10MB を超える)。"""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos, rest = fh.tell(), b""
        while pos > 0:
            step = min(_TAIL_CHUNK, pos)
            pos -= step
            fh.seek(pos)
            parts = (fh.read(step) + rest).split(b"\n")
            rest = parts[0]
            for line in reversed(parts[1:]):
                if line.strip():
                    yield line
        if rest.strip():
            yield rest


def _human(origin) -> bool:
    return isinstance(origin, dict) and origin.get("kind") == "human"


def _blocks_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _typed(row: dict) -> str | None:
    """端末から入った発話ならその本文。 会話を始めた発話か、 claude の作業中に打たれて積まれた発話。"""
    if _human(row.get("origin")) and is_user_prompt(row):
        return _blocks_text((row.get("message") or {}).get("content"))
    queued = row.get("attachment") if row.get("type") == "attachment" else None
    if isinstance(queued, dict) and queued.get("type") == "queued_command" \
            and queued.get("commandMode") == "prompt" and _human(queued.get("origin")):
        return _blocks_text(queued.get("prompt"))
    return None


def last_operator_text(record: Path | None) -> str | None:
    """そのタブで人が最後に打った発話。 最後に端末から入った発話が別のタブからの連絡なら None
    (= 今の作業を始めたのは人ではない)。 記録が読めない時も None。"""
    if record is None:
        return None
    try:
        for raw in _lines_from_the_end(record):
            if b'"user"' not in raw and b"queued_command" not in raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            text = _typed(row) if isinstance(row, dict) else None
            if text is None or not text.strip():
                continue
            text = unwrap_pasted(text).strip()
            return None if text.startswith(OPENING) else text
    except OSError:
        logger.warning("agent message: sender's record could not be read: %s", record)
    return None


def _write_private(text: str) -> Path:
    from backend.config import UPLOADS_TMP  # noqa: PLC0415
    UPLOADS_TMP.mkdir(parents=True, exist_ok=True)
    path = UPLOADS_TMP / f"agent-message-{uuid.uuid4().hex}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


async def _run_check(command: list[str], text: str, names: dict[str, str]) -> tuple[int | None, str]:
    """検査コマンドを 1 回走らせて (終了コード、 理由の 1 行) を返す。 実行できなければ終了コードは None。
    語の中の `{file}` は text を書いた file に、 names の `{名前}` はその値に置き換わる。"""
    path = _write_private(text)
    names = {**names, "file": str(path)}
    argv = []
    for word in command:
        for name, value in names.items():
            word = word.replace("{" + name + "}", value)
        argv.append(os.path.expanduser(word))
    try:
        done = await asyncio.to_thread(subprocess.run, argv, capture_output=True, text=True,
                                       timeout=CHECK_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return None, "the check did not finish in time"
    except OSError as error:
        logger.warning("agent message check could not run: %s", error)
        return None, "the check could not run"
    finally:
        path.unlink(missing_ok=True)
    return done.returncode, (done.stderr.strip().splitlines() or ["the check refused the message"])[-1]


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
    status, reason = await _run_check(AGENT_MESSAGE_CHECK, text, {"session": record.stem})
    if status is None:
        raise_error(503, "agent_message_check_failed", f"連絡の検査を実行できませんでした: {reason}")
    if status != 0:
        logger.info("agent message refused receiver=%s exit=%s", receiver_id, status)
        raise_error(403, "agent_message_refused", f"連絡は届けられませんでした: {reason}", reason=reason)


async def operator_said_for(sender_id: str, receiver_id: str) -> str | None:
    """封筒に入れる人の発話。 無い時と、 `agent_message_operator_check` が通さなかった時は None
    (= 連絡は本文だけで届ける)。 語の `{sender_session}` は送り主の claude の session id。"""
    from backend.config import AGENT_MESSAGE_OPERATOR_CHECK  # noqa: PLC0415
    sender_record = jsonl_path_for_session(sender_id)
    said = last_operator_text(sender_record)
    if said is None or not AGENT_MESSAGE_OPERATOR_CHECK:
        return said
    receiver_record = jsonl_path_for_session(receiver_id)
    if receiver_record is None:
        return None
    status, reason = await _run_check(AGENT_MESSAGE_OPERATOR_CHECK, said,
                                      {"session": receiver_record.stem, "sender_session": sender_record.stem})
    if status != 0:
        logger.info("agent message: operator's words left out sender=%s receiver=%s (%s)", sender_id, receiver_id, reason)
        return None
    return said


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
    said = await operator_said_for(sender, receiver_id)
    result = await pty_send(receiver_id, {"text": envelope(sender, text, said), "enter": True}, None)
    logger.info("agent message sender=%s receiver=%s chars=%d operator_said=%s ok=%s",
                sender, receiver_id, len(text), said is not None, result.get("ok"))
    return {**result, "to": receiver_id, "operator_said": said is not None}
