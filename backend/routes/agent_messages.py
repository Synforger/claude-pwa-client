"""エージェントどうしの連絡 (= あるタブの claude から、 別のタブの claude へ)。

タブの中の claude が `POST /agent-messages` を叩くと、 backend が本文に「誰から」 の封筒を付けて
宛先のタブへ届ける。 アカウントが違うタブどうしでも届く (= backend は全部のタブを知っている)。
受けるのは同じ機械の中からの呼び出しだけ。

別の機械のタブへも送れる (= `config.json` の `agent_message_peers` に相手の backend を書いた時だけ)。
宛先を `<相手の名前>:<タブ>` と書くと、 こちらの backend が検査を済ませてから相手の backend へ渡し
(= `POST /agent-messages/relayed`)、 相手の backend が自分の検査を通して自分のタブへ届ける。 封筒を
書くのは届ける側の backend で、 どの機械から来たかは、 呼び出しの接続元を設定の相手と突き合わせて
決める (= 送り主の言い分では決まらない)。 相手の機械のタブの一覧は `GET /agent-messages/peers`。

相手の機械が答えない時 (= 眠っている・電源か網が落ちている) は、 連絡を失敗にせず、 こちらの backend が預かって、
相手が戻った回に古い順に届ける (= `backend/peers/`。 応答は `outbox: true`)。 連絡には id (= `message_id`) が付き、
相手が同じ id を 2 回受けても 1 回しか打たない (= 送り直しが重なっても二重にならない)。

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

親が自分の子へ届けた連絡は、 送り主が仕事を渡さない連絡と言わない限り (= `hands_work`)、 子への次の仕事として数える: 報告済み (= `完了` / `詰まり`) の子のメモの状態の行を
`作業中` に戻す (= `child_watch/child_work.py`)。 そうしないと、 次の仕事の途中で止まった子を、 止まった子の見回り
も `tabs children` も 「仕事の無い子」 と見る。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Body, Form, HTTPException, Query, Request

from backend._common.local_door import require_this_machine
from backend.jsonl.jsonl_predicates import (
    AGENT_MESSAGE_OPENING as OPENING,
    AGENT_MESSAGE_OPENINGS,
    AGENT_MESSAGE_TAG,
    agent_envelope as _envelope,
    AGENT_MESSAGE_REMOTE_OPENING as REMOTE_OPENING,
    CLIENT_OPENINGS,
    blocks_text,
    is_human_origin,
    is_user_prompt,
    queued_prompt_text,
    unwrap_pasted,
)
from backend import api_tabs
from backend.cli.claude_sessions import running_claudes, status_of
from backend._common.errors import raise_error
from backend.child_watch.child_work import hand_work
from backend._common.state import sessions_meta
from backend.peers import peer_send
from backend.peers.peer_call import (  # noqa: F401 (= re-exported: the tests and the other routes read them here)
    PEER_LIST_TIMEOUT_SEC,
    PEER_TABS_PATH,
    RELAY_TIMEOUT_SEC,
    RELAYED_PATH,
    call_peer,
)
from backend.peers.seen_message_ids import delivering, release
from backend.terminal import input_ready
from backend.terminal.first_message import LAUNCH_DISCOVER_SEC
from backend.terminal.pty_discover import claude_in_pane, register_claude_when_ready
from backend.terminal.receipt import SCREEN_WAIT_SEC, deliver_to_woken, wait_for_claude_screen
from backend.terminal.routes import pty_send
from backend.terminal.runner import has_tmux_session, jsonl_path_for_session, tmux_send_keys
from backend.terminal.session_resolver import (
    ensure_pty_session_for,
    resolve_launch_alias,
    resume_command_for,
    uses_launcher,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 連絡の 1 行目 (= `OPENING` / `REMOTE_OPENING`) と封筒の組み方は、 記録を読む側も使うので
# core/jsonl_predicates.py に置く。
# 記録を末尾から読む時の 1 回分。 1 行がこれより長くても読める (= 足りなければ前へ継ぎ足す)。
_TAIL_CHUNK = 256 * 1024
# 検査コマンドを待つ上限。 外の検査が自分で持つ上限より長く取る (= 先に切ると理由が失われる)。
CHECK_TIMEOUT_SEC = 200.0
# 検査が「どこが当たったか」 として出した行のうち、 送り主へ返す数と 1 行の長さ
HIT_LINES = 20
HIT_LINE_CHARS = 300
# 人の発話を頼まれたのに封筒に入れられなかった理由 (= 返事の `operator_said_left_out`)。
OPERATOR_SAID_NONE = "no_operator_words"
OPERATOR_SAID_REFUSED = "refused"
OPERATOR_SAID_OTHER_MACHINE = "other_machine"
# 連絡の id (= `peers/seen_message_ids.py`)。 送り手の backend が付ける uuid4 の 32 桁
MESSAGE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
LOCAL_TABS_PATH = "/agent-messages/local-tabs"
# What `pty_send` answers with `ok: False` when it typed nothing into the pane (= the claude was not listening, or the
# launch it needed could not be typed).
NOTHING_TYPED_REASONS = ("not_ready", "launch_failed")
# The two answers for a failure nobody foresaw. They differ in the one thing the sender needs to know: whether the
# message may have reached the receiver, since sending it again then can put it there twice.
NOT_SENT_CODE = "agent_message_not_sent"
NOT_SENT_MESSAGE = ("連絡を打つ前に、 backend で想定外のエラーが起きました。 宛先には何も届いていません。 もう一度送ってください。 "
                    "繰り返す時は、 この code と時刻を client のタブへ不具合として送ってください")
UNCONFIRMED_CODE = "agent_message_unconfirmed"
UNCONFIRMED_MESSAGE = ("宛先の端末へ打った後で、 届いたかを確かめられませんでした。 届いているかもしれません。 もう一度送る前に、 "
                       "宛先の会話に届いているかを確かめてください (= 2 通届くのを避けるため)。 繰り返す時は、 この code と時刻を "
                       "client のタブへ不具合として送ってください")


@contextmanager
def failing_as(code: str, message: str) -> Iterator[None]:
    """Turn what the door did not foresee (an exception, or an HTTP error that carries no code) into `code`, so the
    sender is told what happened and what to do next, not a bare 500. Errors that already carry a code pass through."""
    try:
        yield
    except HTTPException as error:
        if isinstance(error.detail, dict) and error.detail.get("code"):
            raise
        logger.warning("agent message: an error with no code became %s: %s %s", code, error.status_code, error.detail)
        raise_error(500, code, message)
    except Exception:
        logger.exception("agent message: an unexpected error became %s", code)
        raise_error(500, code, message)


def resolve_receiver(to: str) -> str:
    """宛先 (= タブの id か、 タブの名前) をタブの id にする。
    An API tab (`backend/api_tabs/`) has no Claude Code to read the message, so it is refused with
    `agent_message_api_tab`; the local send and the relay from another machine both pass here."""
    to = to.strip()
    if to in sessions_meta:
        return to
    named = [m.id for m in sessions_meta.values() if m.title == to]
    if len(named) == 1:
        return named[0]
    if not named and (api_tab := api_tabs.current_table().find(to)) is not None:
        # An API tab has no Claude Code that could read the message: say so, instead of `unknown_receiver`.
        raise_error(409, "agent_message_api_tab",
                    f"宛先は API のタブで、 Claude が居ないので連絡を読む者がいません: {api_tab.id}", to=to, id=api_tab.id)
    if not named:
        raise_error(404, "agent_message_unknown_receiver", f"宛先のタブが見つかりません: {to}", to=to)
    raise_error(409, "agent_message_ambiguous_receiver",
                f"同じ名前のタブが {len(named)} 個あります。 id で指定してください: {', '.join(named)}",
                to=to, ids=", ".join(named))
    raise AssertionError("unreachable")


#: 受け手が、 送り主の読んだ境界を知らない時に封筒へ出す名前 (= タブ名は送り主の働く場所を言う)。
HIDDEN_SENDER = "別の境界のタブ"


def envelope(sender_id: str, text: str, operator_said: str | None = None, title: str | None = None) -> str:
    """本文に「誰から」 を付ける。 中身の側の、 封筒のタグと同じ形の文字列は潰す (= 本文から封筒を
    閉じて外へ文を足すことも、 人の発話を装うことも出来ない)。 `title` は封筒に出す送り主の名前
    (= 省くとタブ名)。"""
    return _envelope(OPENING, sessions_meta[sender_id].title if title is None else title, sender_id, text,
                     operator_said)


def relayed_envelope(peer: str, title: str, session: str, text: str) -> str:
    """別の機械から届いた連絡の封筒。 1 行目は `REMOTE_OPENING`、 `session` は `<相手の名前>:<送り主の
    タブの id>` (= そのまま返事の宛先に書ける)。 相手の名前はこちらの設定の物で、 届いた中身からは
    取らない。 人の発話は入れない (= この機械では確かめられない)。"""
    return _envelope(REMOTE_OPENING, f"{title} @{peer}", f"{peer}:{session}", text)


def lines_from_the_end(path: Path):
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


def entered_text(row: dict) -> str | None:
    """端末から入った発話ならその本文。 会話を始めた発話か、 claude の作業中に打たれて積まれた発話。"""
    if is_human_origin(row.get("origin")) and is_user_prompt(row):
        return blocks_text((row.get("message") or {}).get("content"))
    return queued_prompt_text(row)


def last_operator_text(record: Path | None) -> str | None:
    """そのタブで人が最後に打った発話。 今の作業を始めた発話が別のタブからの連絡か自動の入れ替えの
    発話なら None (= 今の作業を始めたのは人ではない)。 記録が読めない時も None。

    作業の途中に積まれた連絡 (= `queued_command`) は、 その作業を始めた人の発話を隠さない。 人の発話の
    すぐ後に別のタブの連絡が同じ作業へ積まれても、 送り主が答えているのは人の発話だからだ。 1 つの発話の
    頭に連絡が入り、 その後ろに人の言葉が続く時は、 後ろの言葉を人の発話として読む (`_after_messages`)。"""
    if record is None:
        return None
    try:
        for raw in lines_from_the_end(record):
            if b'"user"' not in raw and b"queued_command" not in raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            text = entered_text(row) if isinstance(row, dict) else None
            if text is None or not text.strip():
                continue
            text = unwrap_pasted(text).strip()
            words = _after_messages(text)
            if words and not words.startswith(CLIENT_OPENINGS):
                return words
            if queued_prompt_text(row) is None:
                return None
    except OSError:
        logger.warning("agent message: sender's record could not be read: %s", record)
    return None


def _after_messages(text: str) -> str:
    """`text` without the other tabs' messages at its head (= what follows their envelopes). Claude Code puts what
    waited in the input back into it when a turn is stopped, and what the operator says next is added after it, so one
    prompt can hold a message and then the operator's words. The first closing tag after an opening is the envelope's
    own, since a body cannot write one (`envelope`). → `text` unchanged when it does not begin with a message."""
    closing = f"</{AGENT_MESSAGE_TAG}>"
    while text.startswith(AGENT_MESSAGE_OPENINGS) and closing in text:
        text = text.split(closing, 1)[1].strip()
    return text


def _write_private(text: str) -> Path:
    from backend._common.config import UPLOADS_TMP  # noqa: PLC0415
    UPLOADS_TMP.mkdir(parents=True, exist_ok=True)
    path = UPLOADS_TMP / f"agent-message-{uuid.uuid4().hex}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


async def _run_check(command: list[str], text: str, names: dict[str, str]) -> tuple[int | None, str, list[str]]:
    """検査コマンドを 1 回走らせて (終了コード、 理由の 1 行、 当たった箇所の行) を返す。 実行できなければ
    終了コードは None。 語の中の `{file}` は text を書いた file に、 names の `{名前}` はその値に置き換わる。

    理由は標準エラーの最後の 1 行。 その前に在る字下げされた行 (= 空白 4 つ以上で始まる行) は、 検査が
    「本文のどこが当たったか」 を言っている行として、 字下げを外して返す (= 送り主が直す場所を取り違えない)。"""
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
        return None, "the check did not finish in time", []
    except OSError as error:
        logger.warning("agent message check could not run: %s", error)
        return None, "the check could not run", []
    finally:
        path.unlink(missing_ok=True)
    lines = [line for line in done.stderr.splitlines() if line.strip()]      # 先頭の行の字下げを落とさない
    hits = [line.strip()[:HIT_LINE_CHARS] for line in lines[:-1] if line.startswith("    ")][:HIT_LINES]
    return done.returncode, (lines or ["the check refused the message"])[-1].strip(), hits


async def check(receiver_id: str, text: str) -> None:
    """`agent_message_check` を走らせる。 通れば戻り、 拒否と実行不能は HTTP エラーにする。

    コマンドの語の中の `{file}` は本文を書いた file、 `{session}` は宛先の claude の session id
    (= その会話の記録 file の名前) に置き換わる。
    """
    from backend._common.config import AGENT_MESSAGE_CHECK  # noqa: PLC0415
    if not AGENT_MESSAGE_CHECK:
        return
    record = jsonl_path_for_session(receiver_id)
    if record is None and _message_starts_claude(receiver_id):
        # まだ始まっていない会話: 何も読んでいない相手として通す (= この連絡で始まる会話)
        await judge(f"tier-tab:{receiver_id}", text, receiver_id)
        return
    if record is None:
        raise_error(409, "agent_message_receiver_not_ready",
                    "宛先の会話がまだ始まっていないため、 検査できません")
    await judge(record.stem, text, receiver_id)


async def judge(session: str, text: str, receiver: str) -> None:
    """検査コマンドを、 宛先を `session` として走らせる (= 設定が在る前提)。 通れば戻る。"""
    from backend._common.config import AGENT_MESSAGE_CHECK  # noqa: PLC0415
    status, reason, hits = await _run_check(AGENT_MESSAGE_CHECK, text, {"session": session})
    if status is None:
        raise_error(503, "agent_message_check_failed", f"連絡の検査を実行できませんでした: {reason}")
    if status != 0:
        logger.info("agent message refused receiver=%s exit=%s", receiver, status)
        where = "".join(f"\n  {hit}" for hit in hits)
        raise_error(403, "agent_message_refused", f"連絡は届けられませんでした: {reason}{where}",
                    reason=reason, **({"hits": hits} if hits else {}))


async def sender_title(sender_id: str, receiver_id: str) -> str:
    """封筒に出す送り主の名前。 `agent_message_sender_check` が通した時だけタブ名、 通さない時と実行
    できない時は HIDDEN_SENDER。 設定が無ければタブ名。 語の `{session}` は宛先、 `{sender_session}`
    は送り主の claude の session id。"""
    from backend._common.config import AGENT_MESSAGE_SENDER_CHECK  # noqa: PLC0415
    title = sessions_meta[sender_id].title
    if not AGENT_MESSAGE_SENDER_CHECK:
        return title
    sender_record, receiver_record = jsonl_path_for_session(sender_id), jsonl_path_for_session(receiver_id)
    if sender_record is None or receiver_record is None:
        return HIDDEN_SENDER
    status, reason, _hits = await _run_check(AGENT_MESSAGE_SENDER_CHECK, "",
                                             {"session": receiver_record.stem, "sender_session": sender_record.stem})
    if status != 0:
        logger.info("agent message: sender's name left out sender=%s receiver=%s (%s)", sender_id, receiver_id,
                    reason if status is None else f"exit {status}")
        return HIDDEN_SENDER
    return title


async def operator_said_for(sender_id: str, receiver_id: str) -> tuple[str | None, str | None]:
    """封筒に入れる人の発話と、 入れられない時の理由 (= 送り主へ返す)。 → (発話, None) か (None, 理由)。
    理由は `no_operator_words` (= 今の作業を始めたのが人の発話でない) か `refused` (=
    `agent_message_operator_check` が通さなかった・宛先の記録がまだ無い)。 語の `{sender_session}` は送り主の
    claude の session id。"""
    from backend._common.config import AGENT_MESSAGE_OPERATOR_CHECK  # noqa: PLC0415
    sender_record = jsonl_path_for_session(sender_id)
    said = last_operator_text(sender_record)
    if said is None:
        return None, OPERATOR_SAID_NONE
    if not AGENT_MESSAGE_OPERATOR_CHECK:
        return said, None
    receiver_record = jsonl_path_for_session(receiver_id)
    if receiver_record is None:
        return None, OPERATOR_SAID_REFUSED
    status, reason, _hits = await _run_check(AGENT_MESSAGE_OPERATOR_CHECK, said,
                                      {"session": receiver_record.stem, "sender_session": sender_record.stem})
    if status != 0:
        logger.info("agent message: operator's words left out sender=%s receiver=%s (%s)", sender_id, receiver_id, reason)
        return None, OPERATOR_SAID_REFUSED
    return said, None


# --- 別の機械の backend ----------------------------------------------------------


def split_peer(to: str) -> tuple[str | None, str]:
    """宛先が `<相手の名前>:<タブ>` で、 その名前の相手が設定に在れば (名前, タブ)。 でなければ (None, to)。"""
    from backend._common.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    name, colon, tab = to.strip().partition(":")
    if colon and tab.strip() and name in AGENT_MESSAGE_PEERS:
        return name, tab.strip()
    return None, to


def allowed_for_peer(peer: dict, tab_id: str) -> bool:
    """そのタブが、 この相手と連絡してよいか (= 相手の設定の accounts。 書いていなければ全部のタブ)。"""
    from backend._common.config import default_account_id  # noqa: PLC0415
    accounts = peer.get("accounts")
    meta = sessions_meta[tab_id]
    # the account the tab belongs to, not the one it runs on for now: a tab the account fallback moved is not let
    # through to a machine its own account may not talk to
    return accounts is None or (meta.fallback_from or meta.account_id or default_account_id()) in accounts


def peer_refusal_message(peer_name: str, tab_id: str) -> str:
    """Why a tab may not talk to that machine, for the refusal and for `tabs list`. It names the account the tab
    belongs to, which is what is judged: the one it runs on for now is the one the listing shows."""
    from backend._common.config import default_account_id  # noqa: PLC0415
    meta = sessions_meta[tab_id]
    running_on = meta.account_id or default_account_id()
    own = meta.fallback_from or running_on
    for_now = f"。 今 {running_on} で動いているのは一時の移しで、 判定には使いません" if own != running_on else ""
    return f"このタブは {peer_name} の機械と連絡できません (本来の口座={own}{for_now})"


def peer_of_caller(request: Request) -> tuple[str, dict] | None:
    """呼び出しの接続元が、 設定された相手の物ならその (名前, 設定)。"""
    from backend._common.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    host = request.client.host if request.client else None
    for name, peer in AGENT_MESSAGE_PEERS.items():
        if host is not None and host == peer["address"]:
            return name, peer
    return None


def _tab_running(tab_id: str) -> bool:
    # e2e (= CPC_E2E=1) には本物の claude が居ない。 送信口と同じく、 端末の代わりに記録へ行を足す。
    return os.environ.get("CPC_E2E") == "1" or claude_in_pane(tab_id)


def _message_starts_claude(tab_id: str) -> bool:
    """Whether a message can start the claude of this tab, which has none running. A message does what the
    operator's own action on the tab would do, so the two never differ:

    - without a tmux session, the start the screen makes when it opens the tab (= the last conversation is reopened)
    - with a shell left in the pane, a new conversation (`terminal/first_message.py`) in the tier the tab remembers,
      or `normal` when it remembers none (= what the operator's words start when they name no tier)
    - a child, or an agent without a launcher, with a shell left in the pane: its last conversation is reopened, since
      a child keeps the task its parent gave it and an agent without a launcher cannot start from a first message

    Only an agent without a launcher and with no conversation to reopen is left with no way to start."""
    meta = sessions_meta.get(tab_id)
    if meta is None or _tab_running(tab_id):
        return False
    if not input_ready.is_ready(tab_id):  # already starting: the message waits for it
        return True
    if not has_tmux_session(tab_id):
        return resolve_launch_alias(tab_id) is not None or uses_launcher(tab_id)
    return uses_launcher(tab_id) or resume_command_for(tab_id) is not None


def tab_reachable(tab_id: str) -> bool:
    """Whether a message reaches this tab (= its claude runs, or the message can start it)."""
    return _tab_running(tab_id) or _message_starts_claude(tab_id)


def _reopens_in_its_shell(tab_id: str) -> bool:
    """Whether a shell left in the pane is given back the tab's last conversation, not a new one (= a child, an
    agent without a launcher, or a tab put to sleep, whose conversation must come back)."""
    meta = sessions_meta.get(tab_id)
    return meta is not None and (meta.child or not uses_launcher(tab_id) or meta.sleeping_claude_sid() is not None)


async def wake_tab(tab_id: str) -> bool:
    """Start the tab's claude the way the operator's action would, and wait until it takes input. The sender learns
    here when it did not start, and nothing is typed into a pane that is not listening. A new conversation is left to
    the first message (`pty_send`), which starts it with the message: nothing is started here and no screen is waited
    for, since the pane holds a shell. → True when the tab had no claude running (= the message is then typed by
    `deliver_message`, which makes sure it was taken); False when it was running already.

    A claude that was started or reopened is also waited for until its pane shows Claude's screen: its hooks say it is
    ready before it has read the conversation and drawn the input, and what is typed in between is lost. A tab that is
    being put to sleep is waited for first: what is typed while its claude ends is lost, so the message goes to the
    sleeping tab."""
    # Imported here: the sleep package reads the rollover, which reads this module.
    from backend.sleep.sleeper import wait_until_asleep  # noqa: PLC0415
    await wait_until_asleep(tab_id)
    if _tab_running(tab_id):
        return False
    # A launch still starting is waited for, not typed a second time (= `input_ready.launching`).
    shell_left = has_tmux_session(tab_id) and input_ready.is_ready(tab_id) and not input_ready.launching(tab_id)
    await ensure_pty_session_for(tab_id)
    reopened = False
    if shell_left and _reopens_in_its_shell(tab_id) and (command := resume_command_for(tab_id)) is not None:
        input_ready.mark_starting(tab_id)
        if not (tmux_send_keys(tab_id, key="C-u") and tmux_send_keys(tab_id, text=command, enter=True)):
            input_ready.mark_ready(tab_id)
            raise_error(409, "agent_message_receiver_not_ready", "宛先の claude を起動できませんでした。 もう一度送ってください")
        logger.info("agent message: reopened the last conversation in the shell session=%s", tab_id)
        asyncio.create_task(register_claude_when_ready(tab_id, max_wait=LAUNCH_DISCOVER_SEC))
        reopened = True
    starting = reopened or input_ready.launching(tab_id)
    if not await input_ready.wait_ready(tab_id, LAUNCH_DISCOVER_SEC):
        raise_error(409, "agent_message_receiver_not_ready",
                    f"宛先の claude が {LAUNCH_DISCOVER_SEC:.0f} 秒以内に起動しませんでした。 もう一度送ってください")
    if not starting and not claude_in_pane(tab_id):
        return True  # nothing started: the pane holds a shell, and the message's own typing starts the conversation
    if not await wait_for_claude_screen(tab_id):
        # The screen is recognised by Claude's status bar, which not every installation shows: typing anyway is safe,
        # since what is typed to a woken tab is checked for receipt and put right once (`deliver_to_woken`).
        logger.warning("agent message: the screen of session=%s did not look like Claude's within %.0fs; typing anyway",
                       tab_id, SCREEN_WAIT_SEC)
    return True


async def deliver_message(tab_id: str, text: str, woke: bool) -> dict:
    """Type `text` (= a message already in its envelope) into the tab and press Enter. A tab that `wake_tab` started
    (`woke`) is only said to have taken it when its record shows the message (after one rescue, see
    `terminal/receipt.py`); otherwise 409 `agent_message_not_taken`. A tab that was running already gets the plain
    `pty_send`, whose answer is that of the typing: an answer that says it did not type is refused with the code that
    tells the sender whether the message may have arrived (`refuse_untyped`)."""
    if not woke:
        result = await pty_send(tab_id, {"text": text, "enter": True}, None)
        if not result.get("ok"):
            refuse_untyped(result)
        return result
    if not await deliver_to_woken(tab_id, text):
        raise_error(409, "agent_message_not_taken", "宛先が受け取りませんでした。 もう一度送ってください")
    return {"ok": True, "confirmed": True}


def refuse_untyped(result: dict) -> None:
    """Refuse a delivery whose `pty_send` answered `ok: False`. A claude that was not listening, or a launch that could
    not be typed, means nothing reached the receiver (`agent_message_receiver_not_ready`: send again). An answer with no
    reason is a typing that stopped part way, which may have left the message in the receiver's input
    (`agent_message_unconfirmed`: check before sending again)."""
    if result.get("reason") in NOTHING_TYPED_REASONS:
        raise_error(409, "agent_message_receiver_not_ready",
                    "宛先の claude が入力を受け付ける状態になりませんでした。 何も打っていません。 もう一度送ってください")
    raise_error(500, UNCONFIRMED_CODE, UNCONFIRMED_MESSAGE)


def _forget_if_not_delivered(message_id: str | None, result: dict) -> None:
    """A delivery that answered `ok: false` without raising leaves `delivering` taking the id for delivered: forget it,
    or the sender's next try with the same id would be dropped as a duplicate and the message lost."""
    if message_id is not None and not result.get("ok"):
        release(message_id)


async def deliver_or_keep(tab_id: str, text: str) -> dict:
    """Deliver `text` (= a message in its envelope), or keep it without waking the tab when the account hold has the
    tab stopped and no account is clear for it to run on (`account_hold/hold_mail.py`): the hold hands it over once one
    is. → the answer of the delivery, or `{"ok": True, "kept": True}`."""
    # Imported here: the account hold imports the account fallback, which sends its messages through this module.
    from backend.account_hold import hold_mail  # noqa: PLC0415
    # Up to the typing of the message nothing reached the receiver, so an error there says so; from the typing on it
    # may have.
    with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
        if await asyncio.to_thread(hold_mail.must_keep, tab_id):
            hold_mail.keep(tab_id, text)
            return {"ok": True, "kept": True}
        woke = await wake_tab(tab_id)
    with failing_as(UNCONFIRMED_CODE, UNCONFIRMED_MESSAGE):
        return await deliver_message(tab_id, text, woke)


async def send_to_peer(peer_name: str, tab: str, sender: str, text: str) -> dict:
    """別の機械のタブへの連絡。 こちらの検査を通してから相手の backend へ渡す (= `peers/peer_send.py`)。
    相手が答えない時は、 失敗にせず預かる (= 戻った時に届ける。 答えは `outbox: true`)。

    検査には、 宛先の session id の代わりに `<相手の名前>:<タブ>` を渡す (= この機械のどの会話でもない
    名前)。 人の発話は付けない (= 頼まれても。 機械を跨ぐと、 受け取る側で本物か確かめられない)。
    """
    from backend._common.config import AGENT_MESSAGE_CHECK, AGENT_MESSAGE_PEERS  # noqa: PLC0415
    peer = AGENT_MESSAGE_PEERS[peer_name]
    name = f"{peer_name}:{tab}"
    if not allowed_for_peer(peer, sender):
        raise_error(403, "agent_message_peer_not_allowed", peer_refusal_message(peer_name, sender), peer=peer_name)
    if AGENT_MESSAGE_CHECK:
        await judge(name, text, name)
    # From the call on, the other machine may have delivered the message whatever happens to the answer.
    with failing_as(UNCONFIRMED_CODE, UNCONFIRMED_MESSAGE):
        answer = await peer_send.send(peer_name, peer, tab=tab, sender=sender, title=sessions_meta[sender].title,
                                      text=text)
    logger.info("agent message sender=%s receiver=%s chars=%d operator_said=False ok=%s outbox=%s",
                sender, name, len(text), answer.get("ok"), answer.get("outbox", False))
    return answer


@router.post("/agent-messages")
async def post_agent_message(
    request: Request,
    to: str = Form(...),
    sender: str = Form(..., alias="from"),
    text: str = Form(...),
    operator_said: bool = Form(False),
    hands_work: str | None = Form(None),
    message_id: str | None = Form(None),
) -> dict:
    """タブの中の claude が、 別のタブの claude へ連絡を送る。

    form:
        to            (str):  宛先のタブの id、 またはタブの名前 (= 同じ名前が複数あれば id で)
        from          (str):  送り主のタブの id (= そのタブの環境変数 `PWA_SID`)
        text          (str):  本文
        operator_said (bool): 送り主のタブで人が最後に打った発話を封筒に入れるか (= 既定は入れない)
        hands_work    (str):  宛先が送り主の子の時、 次の仕事を渡す連絡か。 `false` の時だけ渡さない (= 受け取りの知らせ
                              など)。 真偽の欄にしないのは、 form で送られなかった真偽の欄を FastAPI が既定によらず
                              false として受けるため
        message_id    (str):  連絡の id (= uuid4 の 32 桁。 `tabs send` が 1 回の起動ごとに付ける)。 同じ id が 2 回目に
                              来たら、 打たずに `{"ok": true, "duplicate": true}` を返す (= `peers/seen_message_ids.py`)。
                              別の機械宛ての連絡には使わない (= 送り手の backend が自分で付ける)
    """
    require_this_machine(request, "agent_message_local_only")
    if sender not in sessions_meta:
        raise_error(400, "agent_message_unknown_sender", f"送り主のタブが見つかりません: {sender}", sender=sender)
    if not text.strip():
        raise_error(400, "agent_message_empty", "本文が空です")
    if message_id is not None and not MESSAGE_ID_RE.match(message_id):
        raise_error(400, "agent_message_bad_id", "連絡の id は uuid4 の 32 桁 (小文字の 16 進) で書いてください")
    peer_name, tab = split_peer(to)
    if peer_name is not None:
        result = await send_to_peer(peer_name, tab, sender, text)
        return {**result, "operator_said_left_out": OPERATOR_SAID_OTHER_MACHINE} if operator_said else result
    with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
        receiver_id = resolve_receiver(to)
        if receiver_id == sender:
            raise_error(400, "agent_message_to_self", "自分のタブへは送れません")
    with delivering(message_id) as first:
        if not first:
            return {"ok": True, "duplicate": True, "to": receiver_id, "operator_said": False}
        with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
            if not tab_reachable(receiver_id):
                raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いておらず、 起動できません")
            await check(receiver_id, text)
            said, left_out = await operator_said_for(sender, receiver_id) if operator_said else (None, None)
            title = await sender_title(sender, receiver_id)
            message = envelope(sender, text, said, title)
        result = await deliver_or_keep(receiver_id, message)
    _forget_if_not_delivered(message_id, result)
    logger.info("agent message sender=%s receiver=%s chars=%d operator_said=%s ok=%s kept=%s",
                sender, receiver_id, len(text), said is not None, result.get("ok"), result.get("kept", False))
    if (hands_work or "").strip().lower() != "false":
        await hand_over_work(sender, receiver_id)
    answer = {**result, "to": receiver_id, "operator_said": said is not None}
    return {**answer, "operator_said_left_out": left_out} if left_out is not None else answer


async def hand_over_work(sender: str, receiver_id: str) -> None:
    """Count the message as the receiver's next work when the receiver is the sender's child. The message has been
    delivered by now, so a memo that cannot be written is logged and does not turn the delivery into a failure."""
    try:
        await asyncio.to_thread(hand_work, sender, receiver_id)
    except Exception:
        logger.exception("agent message: the child's memo could not be set back to working child=%s", receiver_id)


def require_peer(request: Request) -> tuple[str, dict]:
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
        message_id    (str): 連絡の id (= 送り手の backend が付ける uuid4 の 32 桁。 無くてもよい: 古い backend の連絡)。
                             同じ id を既に届けていたら、 打たずに `{"ok": true, "duplicate": true}` を返す。 届けている
                             途中なら 409 `agent_message_in_flight` (= 送り手は預かりに残して次の回に送り直す)
    """
    peer_name, peer = require_peer(request)
    to, title, session, text = (body.get(k) for k in ("to", "from_title", "from_session", "text"))
    message_id = body.get("message_id")
    if not all(isinstance(v, str) and v.strip() for v in (to, title, session, text)) or not (
            message_id is None or (isinstance(message_id, str) and MESSAGE_ID_RE.match(message_id))):
        raise_error(400, "agent_message_bad_relay", "相手の機械から届いた連絡の形が正しくありません")
    with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
        receiver_id = resolve_receiver(to)
        if not allowed_for_peer(peer, receiver_id):
            raise_error(403, "agent_message_peer_not_allowed",
                        f"宛先のタブは {peer_name} の機械と連絡できません", peer=peer_name)
    with delivering(message_id) as first:
        if not first:
            logger.info("agent message peer=%s message_id=%s was delivered already", peer_name, message_id)
            return {"ok": True, "duplicate": True, "to": receiver_id, "operator_said": False}
        with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
            if not tab_reachable(receiver_id):
                raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いておらず、 起動できません")
            await check(receiver_id, text)
            message = relayed_envelope(peer_name, title, session, text)
        result = await deliver_or_keep(receiver_id, message)
    _forget_if_not_delivered(message_id, result)
    logger.info("agent message peer=%s sender=%s receiver=%s chars=%d operator_said=False ok=%s kept=%s",
                peer_name, session, receiver_id, len(text), result.get("ok"), result.get("kept", False))
    return {**result, "to": receiver_id, "operator_said": False}


@router.get(PEER_TABS_PATH)
async def get_tabs_for_peer(request: Request) -> dict:
    """相手の機械へ、 この機械のタブの一覧を返す (= その相手と連絡してよいタブだけ。 眠っているタブ・claude の居ないタブも
    含める)。 `running` は連絡が届くか、 `status` は動いている claude の状態 (= 居なければ null)、 `asleep` は眠らせて
    あるか。 `status` と `asleep` で、 相手の `tabs list` はこの機械の `tabs list` と同じ状態の語を出す。"""
    _peer_name, peer = require_peer(request)
    claudes = await asyncio.to_thread(running_claudes)
    return {"tabs": [{"id": m.id, "title": m.title, "running": tab_reachable(m.id),
                      "status": status_of(claudes.get(m.id)), "asleep": m.sleep is not None}
                     for m in sessions_meta.values() if allowed_for_peer(peer, m.id)]}


@router.get(LOCAL_TABS_PATH)
async def get_local_tabs(request: Request) -> dict:
    """Whether each tab of this machine takes a message, the conversation it last ran, and whether it was put to sleep
    (= `backend/sleep/`), for `tabs list` (= a tab with no claude is not in Claude Code's own records). Callable only
    from this machine."""
    require_this_machine(request, "agent_message_local_only")
    tabs = []
    for tab_id in list(sessions_meta):
        record = jsonl_path_for_session(tab_id)
        tabs.append({"id": tab_id, "reachable": tab_reachable(tab_id), "conversation": record.stem if record else None,
                     "asleep": sessions_meta[tab_id].sleep is not None})
    return {"tabs": tabs}


@router.get("/agent-messages/peers")
async def get_peers(request: Request, caller: str | None = Query(None, alias="from")) -> dict:
    """設定された相手の機械と、 そこで連絡を受けられるタブの一覧 (= 同じ機械の中からだけ呼べる)。

    繋がらない相手は `tabs` が null で、 `error` に理由が入る。
    With `from` (= the tab that asks), a machine that tab may not talk to carries `refusal`, the sentence of the refusal.
    Its tabs are still listed: the listing also tells which tabs of the other machine exist.
    """
    from backend._common.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    require_this_machine(request, "agent_message_local_only")
    peers = []
    for name, peer in AGENT_MESSAGE_PEERS.items():
        reply = await call_peer(name, peer, PEER_TABS_PATH, timeout=PEER_LIST_TIMEOUT_SEC)
        if reply.status == 200 and isinstance(reply.body.get("tabs"), list):
            peers.append({"name": name, "tabs": reply.body["tabs"], "error": None})
        else:
            detail = reply.body.get("detail") if isinstance(reply.body.get("detail"), dict) else {}
            peers.append({"name": name, "tabs": None,
                          "error": detail.get("code") or ("unreachable" if reply.status is None else f"http_{reply.status}")})
        if caller in sessions_meta and not allowed_for_peer(peer, caller):
            peers[-1]["refusal"] = peer_refusal_message(name, caller)
    return {"peers": peers}
