"""エージェントどうしの連絡 (= あるタブの claude から、 別のタブの claude へ)。

タブの中の claude が `POST /agent-messages` を叩くと、 backend が本文に「誰から」 の封筒を付けて
宛先のタブへ届ける。 アカウントが違うタブどうしでも届く (= backend は全部のタブを知っている)。
受けるのは同じ機械の中からの呼び出しだけ。

別の機械のタブへも送れる (= `config.json` の `agent_message_peers` に相手の backend を書いた時だけ)。
宛先を `<相手の名前>:<タブ>` と書くと、 こちらの backend が検査を済ませてから相手の backend へ渡し
(= `POST /agent-messages/relayed`)、 相手の backend が自分の検査を通して自分のタブへ届ける。 封筒を
書くのは届ける側の backend で、 どの機械から来たかは、 呼び出しの接続元を設定の相手と突き合わせて
決める (= 送り主の言い分では決まらない)。 相手の機械のタブの一覧は `GET /agent-messages/peers`。

別の機械から届いた連絡は、 1 行目が別の文になる (= `REMOTE_OPENING`)。 受け取った側の claude と、
端末の入力を読む外の道具が、 「この機械の外から来た」 を 1 行目だけで見分けられる。 **人の発話は
機械を跨がない**: `<operator-said>` を書けるのは、 その発話が打たれた機械の backend だけで、 別の機械の
backend が「人がこう打った」 と言ってきても、 こちらには確かめる手段が無い (= 相手の機械に入られていれば、
その言葉も作れる)。 送る側は付けず、 受ける側は届いても読まない。

人が打つ送信口 (= `/pty/{sid}/send`) とは別の口にしてある。 宛先の claude から見ると、 どちらも
端末に打たれた文として届くので、 区別は本文の 1 行目 (= `OPENING`) でしか付かない。 この口を通った
連絡には必ずその行が付き、 人の送信には付かない。

送り主が頼んだ時だけ (= `operator_said`)、 送り主のタブで人が最後に打った発話も封筒に入れて届ける
(= `<operator-said>`)。 宛先の claude は、 連絡が人の指示から出た物かを、 送り主の言い分ではなく人の
言葉そのもので判断できる。 送り主が決められるのは付けるかどうかだけで、 中身は backend が記録から読む。
頼まれなければ付けない ― 人の最後の発話は、 その連絡の用件と関係が無いことの方が多い (= 用件と無関係な
発話が、 宛先のタブへの指示として届く)。 送り主の今の作業が別のタブからの連絡で始まっていた時は、
頼まれても付けない。

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
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Form, Request

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
# 別の機械のタブから届いた連絡の 1 行目。 こちらも固定で、 同じ機械の中の連絡とは別の文にする
# (= 1 行目だけで「この機械の外から来た」 と分かる)。
REMOTE_OPENING = "Message from a session on another machine, relayed by the client (the operator did not type this):"
OPENINGS = (OPENING, REMOTE_OPENING)
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
# 相手の backend を待つ上限。 相手も届ける前に自分の検査を走らせるので、 その上限より長く取る。
RELAY_TIMEOUT_SEC = 240.0
# 相手のタブの一覧を待つ上限。 相手が落ちている時に、 一覧を打った側を待たせない (= 検査は走らないので短くてよい)。
PEER_LIST_TIMEOUT_SEC = 10.0
# 相手の backend どうしが呼び合う口 (= 設定された相手の接続元からだけ受ける)。
RELAYED_PATH = "/agent-messages/relayed"
PEER_TABS_PATH = "/agent-messages/tabs"


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


def _attr(value: str) -> str:
    """封筒の欄に入れる値。 欄を閉じる文字と改行を潰し、 封筒のタグと同じ形の文字列も本文と同じに潰す。"""
    return _TAG_LIKE.sub(r"&lt;\1\2", value.replace('"', "'").replace("\n", " "))


def _envelope(opening: str, title: str, session: str, text: str, operator_said: str | None = None) -> str:
    said = f"<{OPERATOR_TAG}>\n{_plain(operator_said)}\n</{OPERATOR_TAG}>\n" if operator_said else ""
    return f'{opening}\n<{TAG} from="{_attr(title)}" session="{_attr(session)}">\n{said}{_plain(text)}\n</{TAG}>'


def envelope(sender_id: str, text: str, operator_said: str | None = None) -> str:
    """本文に「誰から」 を付ける。 中身の側の、 封筒のタグと同じ形の文字列は潰す (= 本文から封筒を
    閉じて外へ文を足すことも、 人の発話を装うことも出来ない)。"""
    return _envelope(OPENING, sessions_meta[sender_id].title, sender_id, text, operator_said)


def relayed_envelope(peer: str, title: str, session: str, text: str) -> str:
    """別の機械から届いた連絡の封筒。 1 行目は `REMOTE_OPENING`、 `session` は `<相手の名前>:<送り主の
    タブの id>` (= そのまま返事の宛先に書ける)。 相手の名前はこちらの設定の物で、 届いた中身からは
    取らない。 人の発話は入れない (= この機械では確かめられない)。"""
    return _envelope(REMOTE_OPENING, f"{title} @{peer}", f"{peer}:{session}", text)


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
            return None if text.startswith(OPENINGS) else text
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
    await _judge(record.stem, text, receiver_id)


async def _judge(session: str, text: str, receiver: str) -> None:
    """検査コマンドを、 宛先を `session` として走らせる (= 設定が在る前提)。 通れば戻る。"""
    from backend.config import AGENT_MESSAGE_CHECK  # noqa: PLC0415
    status, reason = await _run_check(AGENT_MESSAGE_CHECK, text, {"session": session})
    if status is None:
        raise_error(503, "agent_message_check_failed", f"連絡の検査を実行できませんでした: {reason}")
    if status != 0:
        logger.info("agent message refused receiver=%s exit=%s", receiver, status)
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


# --- 別の機械の backend ----------------------------------------------------------


def split_peer(to: str) -> tuple[str | None, str]:
    """宛先が `<相手の名前>:<タブ>` で、 その名前の相手が設定に在れば (名前, タブ)。 でなければ (None, to)。"""
    from backend.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    name, colon, tab = to.strip().partition(":")
    if colon and tab.strip() and name in AGENT_MESSAGE_PEERS:
        return name, tab.strip()
    return None, to


def allowed_for_peer(peer: dict, tab_id: str) -> bool:
    """そのタブが、 この相手と連絡してよいか (= 相手の設定の accounts。 書いていなければ全部のタブ)。"""
    from backend.config import default_account_id  # noqa: PLC0415
    accounts = peer.get("accounts")
    return accounts is None or (sessions_meta[tab_id].account_id or default_account_id()) in accounts


def peer_of_caller(request: Request) -> tuple[str, dict] | None:
    """呼び出しの接続元が、 設定された相手の物ならその (名前, 設定)。"""
    from backend.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    host = request.client.host if request.client else None
    for name, peer in AGENT_MESSAGE_PEERS.items():
        if host is not None and host == peer["address"]:
            return name, peer
    return None


def _call_peer(url: str, payload: dict | None, timeout: float) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (= url は設定の物)
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


async def call_peer(name: str, peer: dict, path: str, payload: dict | None = None,
                    timeout: float = RELAY_TIMEOUT_SEC) -> tuple[int | None, dict]:
    """相手の backend を 1 回呼んで (HTTP の状態, 本文) を返す。 繋がらなければ状態は None。"""
    try:
        return await asyncio.to_thread(_call_peer, peer["url"] + path, payload, timeout)
    except OSError as error:
        logger.warning("agent message: peer %s could not be reached: %s", name, error)
        return None, {}


def _tab_running(tab_id: str) -> bool:
    # e2e (= CPC_E2E=1) には本物の claude が居ない。 送信口と同じく、 端末の代わりに記録へ行を足す。
    return os.environ.get("CPC_E2E") == "1" or claude_in_pane(tab_id)


async def send_to_peer(peer_name: str, tab: str, sender: str, text: str) -> dict:
    """別の機械のタブへの連絡。 こちらの検査を通してから相手の backend へ渡す。

    検査には、 宛先の session id の代わりに `<相手の名前>:<タブ>` を渡す (= この機械のどの会話でもない
    名前)。 人の発話は付けない (= 頼まれても。 機械を跨ぐと、 受け取る側で本物か確かめられない)。
    """
    from backend.config import AGENT_MESSAGE_CHECK, AGENT_MESSAGE_PEERS  # noqa: PLC0415
    peer = AGENT_MESSAGE_PEERS[peer_name]
    name = f"{peer_name}:{tab}"
    if not allowed_for_peer(peer, sender):
        raise_error(403, "agent_message_peer_not_allowed",
                    f"このタブは {peer_name} の機械と連絡できません", peer=peer_name)
    if AGENT_MESSAGE_CHECK:
        await _judge(name, text, name)
    status, body = await call_peer(peer_name, peer, RELAYED_PATH, {
        "to": tab, "from_title": sessions_meta[sender].title, "from_session": sender, "text": text,
    })
    if status is None:
        raise_error(502, "agent_message_peer_unreachable", f"{peer_name} の機械に繋がりませんでした", peer=peer_name)
    if status != 200:
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        params = {k: v for k, v in (detail.get("params") or {}).items() if k not in ("status_code", "code", "message")}
        raise_error(status if 400 <= status < 600 else 502, detail.get("code") or "agent_message_peer_failed",
                    detail.get("message") or f"{peer_name} の機械が連絡を受け取りませんでした (HTTP {status})",
                    **{**params, "peer": peer_name})
    logger.info("agent message sender=%s receiver=%s chars=%d operator_said=False ok=%s",
                sender, name, len(text), body.get("ok"))
    return {**body, "to": f"{peer_name}:{body.get('to', tab)}", "operator_said": False}


@router.post("/agent-messages")
async def post_agent_message(
    request: Request,
    to: str = Form(...),
    sender: str = Form(..., alias="from"),
    text: str = Form(...),
    operator_said: bool = Form(False),
) -> dict:
    """タブの中の claude が、 別のタブの claude へ連絡を送る。

    form:
        to            (str):  宛先のタブの id、 またはタブの名前 (= 同じ名前が複数あれば id で)
        from          (str):  送り主のタブの id (= そのタブの環境変数 `PWA_SID`)
        text          (str):  本文
        operator_said (bool): 送り主のタブで人が最後に打った発話を封筒に入れるか (= 既定は入れない)
    """
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        logger.warning("agent message rejected: non-local client=%s", client_host)
        raise_error(403, "agent_message_local_only", "この口は同じ機械の中からだけ使えます")
    if sender not in sessions_meta:
        raise_error(400, "agent_message_unknown_sender", f"送り主のタブが見つかりません: {sender}", sender=sender)
    if not text.strip():
        raise_error(400, "agent_message_empty", "本文が空です")
    peer_name, tab = split_peer(to)
    if peer_name is not None:
        return await send_to_peer(peer_name, tab, sender, text)
    receiver_id = resolve_receiver(to)
    if receiver_id == sender:
        raise_error(400, "agent_message_to_self", "自分のタブへは送れません")
    if not _tab_running(receiver_id):
        # 連絡で会話を起こさない: 新しい会話は最初の発話で起動の仕方が決まる。
        raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いていません")
    await check(receiver_id, text)
    said = await operator_said_for(sender, receiver_id) if operator_said else None
    result = await pty_send(receiver_id, {"text": envelope(sender, text, said), "enter": True}, None)
    logger.info("agent message sender=%s receiver=%s chars=%d operator_said=%s ok=%s",
                sender, receiver_id, len(text), said is not None, result.get("ok"))
    return {**result, "to": receiver_id, "operator_said": said is not None}


def _require_peer(request: Request) -> tuple[str, dict]:
    caller = peer_of_caller(request)
    if caller is None:
        logger.warning("agent message rejected: client=%s is not a configured peer",
                       request.client.host if request.client else None)
        raise_error(403, "agent_message_unknown_peer", "この口は、 設定された相手の機械からだけ使えます")
    return caller


@router.post(RELAYED_PATH)
async def post_relayed_agent_message(request: Request, body: dict = Body(...)) -> dict:
    """別の機械の backend が、 自分のタブから預かった連絡をこの機械のタブへ届ける。

    受けるのは、 `agent_message_peers` に書いた相手の接続元からの呼び出しだけ。 届ける前に、 この機械の
    検査 (= `agent_message_check`) を本文に掛ける。 届ける封筒の 1 行目は `REMOTE_OPENING` で、 人の発話は
    入れない (= 相手が何を送ってきても。 上の 4 つ以外の項目は読まない)。

    json:
        to            (str): 宛先のタブの id か名前 (= この機械のタブ)
        from_title    (str): 送り主のタブの名前
        from_session  (str): 送り主のタブの id (= 相手の機械での id)
        text          (str): 本文
    """
    peer_name, peer = _require_peer(request)
    to, title, session, text = (body.get(k) for k in ("to", "from_title", "from_session", "text"))
    if not all(isinstance(v, str) and v.strip() for v in (to, title, session, text)):
        raise_error(400, "agent_message_bad_relay", "相手の機械から届いた連絡の形が正しくありません")
    receiver_id = resolve_receiver(to)
    if not allowed_for_peer(peer, receiver_id):
        raise_error(403, "agent_message_peer_not_allowed",
                    f"宛先のタブは {peer_name} の機械と連絡できません", peer=peer_name)
    if not _tab_running(receiver_id):
        raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いていません")
    await check(receiver_id, text)
    payload = {"text": relayed_envelope(peer_name, title, session, text), "enter": True}
    result = await pty_send(receiver_id, payload, None)
    logger.info("agent message peer=%s sender=%s receiver=%s chars=%d operator_said=False ok=%s",
                peer_name, session, receiver_id, len(text), result.get("ok"))
    return {**result, "to": receiver_id, "operator_said": False}


@router.get(PEER_TABS_PATH)
async def get_tabs_for_peer(request: Request) -> dict:
    """相手の機械へ、 連絡を受けられるこの機械のタブの一覧を返す (= その相手と連絡してよいタブだけ)。"""
    _peer_name, peer = _require_peer(request)
    return {"tabs": [{"id": m.id, "title": m.title, "running": _tab_running(m.id)}
                     for m in sessions_meta.values() if allowed_for_peer(peer, m.id)]}


@router.get("/agent-messages/peers")
async def get_peers(request: Request) -> dict:
    """設定された相手の機械と、 そこで連絡を受けられるタブの一覧 (= 同じ機械の中からだけ呼べる)。

    繋がらない相手は `tabs` が null で、 `error` に理由が入る。
    """
    from backend.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        raise_error(403, "agent_message_local_only", "この口は同じ機械の中からだけ使えます")
    peers = []
    for name, peer in AGENT_MESSAGE_PEERS.items():
        status, body = await call_peer(name, peer, PEER_TABS_PATH, timeout=PEER_LIST_TIMEOUT_SEC)
        if status == 200 and isinstance(body.get("tabs"), list):
            peers.append({"name": name, "tabs": body["tabs"], "error": None})
        else:
            detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
            peers.append({"name": name, "tabs": None,
                          "error": detail.get("code") or ("unreachable" if status is None else f"http_{status}")})
    return {"peers": peers}
