"""送信本文 (= text / slash command) が tmux 経由で claude に届いたかを JSONL から確認する。

`pty_routes` の endpoint (= /pty/{sid}/send, /send-with-files) から呼ばれる。 旧実装は
pty_routes.py に同居していたが、 純粋な「JSONL カウント + wait + 救済再送」 の責務なので分離した。

挙動:
    1. 送信直前に jsonl_path の現在 file size (= initial_pos) を取る
    2. tmux send-keys が成功したら _confirm_after_send を呼ぶ
    3. initial_pos から差分行だけ tail (= read_complete_lines) で読み、 該当 user 行が +1 されるか
       を 4s 監視 → 出なければ Enter だけ追い打ちして 1s 再監視
    4. 確認できなくても再ペーストはせず ok:True を返す (= 二重発火を避ける)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from backend.jsonl.predicates import is_user_prompt as _is_user_prompt_pred
from backend.jsonl.tail import read_complete_lines
from backend.terminal.runner import get_pane_cursor_y, tmux_send_keys

logger = logging.getLogger(__name__)

# slash command (= /deep-research, /clear 等) を素プロンプトと区別して数える。
# `_count_user_prompts` が harness XML として除外する `<command-name>` 行をこちらで拾う。
_COMMAND_NAME_RE = re.compile(r"^\s*<command-name\b")


def _count_in_lines(lines, predicate) -> int:
    """JSONL string lines のうち predicate(parsed_dict) が True のものを数える。
    user 行で sidechain / meta は最初に除外する (= 全 counter 共通)。"""
    count = 0
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
            continue
        if predicate(d):
            count += 1
    return count


def _is_plain_user_prompt(d: dict) -> bool:
    """素プロンプト (= 実ユーザ発言): harness XML / interrupt marker / 空文字 を除外。

    W1-C 引継: 旧版は events.HARNESS_XML_RE / INTERRUPT_USER_RE を直 import して独自実装
    していたが、 session_status.is_user_prompt と判定がズレる潜在 race があった
    (= backend-F-05)。 真値は predicates.is_user_prompt に集約済みなのでそこに委譲する。
    `_count_in_lines` が事前に type=="user" / sidechain / meta を弾いてるが、 predicates
    も同じ gate を持つので redundant でも安全。
    """
    return _is_user_prompt_pred(d)


def _is_command_line(d: dict) -> bool:
    """slash command の harness XML `<command-name>` 行。"""
    c = (d.get("message") or {}).get("content")
    return isinstance(c, str) and bool(_COMMAND_NAME_RE.match(c.strip()))


def _count_user_prompts(path, from_pos: int = 0) -> tuple[int, int]:
    """from_pos 以降の JSONL を読んで素プロンプト件数と次回 from_pos を返す。

    旧 signature (path のみ) は file 全体を毎回読み直していたが、 wait ループ (= 50 回 poll)
    で大型 JSONL を read し直すコストが増える。 from_pos 起点で `read_complete_lines` を使う
    ことで初回以降は新規行だけ走査する。 初回呼び出しは from_pos=0 で従来通り (= 全読み)。"""
    if not path:
        return (0, 0)
    try:
        lines, end_pos = read_complete_lines(path, from_pos)
    except OSError:
        return (0, from_pos)
    return (_count_in_lines(lines, _is_plain_user_prompt), end_pos)


def _count_command_lines(path, from_pos: int = 0) -> tuple[int, int]:
    """from_pos 以降の `<command-name>` user 行件数と次回 from_pos を返す (slash 確認用)。"""
    if not path:
        return (0, 0)
    try:
        lines, end_pos = read_complete_lines(path, from_pos)
    except OSError:
        return (0, from_pos)
    return (_count_in_lines(lines, _is_command_line), end_pos)


async def _wait_count_added(counter, path, initial_pos: int, timeout: float) -> bool:
    """counter(path, pos) -> (new_count, new_pos) が new_count > 0 を返すまで wait。

    initial_pos = 呼出時点のファイルサイズ (= initial_count 取得済の境界)。 以降は new_pos を
    引き継いで差分だけ読む (= 全読みなし)。"""
    poll = 0.1
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    pos = initial_pos
    while loop.time() < deadline:
        n, pos = counter(path, pos)
        if n > 0:
            return True
        await asyncio.sleep(poll)
    n, _ = counter(path, pos)
    return n > 0


def _delivery_counter(text: str):
    """送信本文に応じた確認カウンタを返す。 slash command は `<command-name>` 行、
    素プロンプトは素の user 行で確認する。 返り値 (counter, is_slash)。"""
    is_slash = bool(text) and text.lstrip().startswith("/")
    return (_count_command_lines if is_slash else _count_user_prompts), is_slash


async def _confirm_after_send(session_id, text, jsonl_path, initial_pos, is_slash) -> dict:
    """送信直後の確認 + 取りこぼし救済 (= text 経路 / 添付経路 共通)。

    initial_pos = 送信直前のファイルサイズ。 そこから新規 user 行 (slash なら `<command-name>`、
    そうでなければ素プロンプト) が出るかを 4s 監視 → 出なければ Enter だけ追い打ちして 1s 再監視。
    それでも確認できなくても再ペーストはせず ok:True を返す。

    backend-F-22: Enter 救済前に tmux pane の cursor_y を見て、 prompt 行に居る (= text
    が pane に渡ってない、 送信失敗) のか、 行が降りてる (= text 入力中、 Enter で確定
    すべき) のかを区別する。 cursor_y == 0 なら救済 Enter は無意味 (= 空 Enter で空行を
    挿入するだけ) なので skip。 取得失敗 (= 旧経路 / tmux 不在 等) は従来挙動どおり Enter
    を打つ (= 安全側)。"""
    counter = _count_command_lines if is_slash else _count_user_prompts
    if await _wait_count_added(counter, jsonl_path, initial_pos, timeout=4.0):
        return {"ok": True, "confirmed": True}
    cursor_y = get_pane_cursor_y(session_id)
    if cursor_y == 0:
        logger.warning(
            "pty_send: no prompt within 4s and cursor at row 0 (text not buffered): "
            "sid=%s text_len=%d slash=%s",
            session_id, len(text or ""), is_slash,
        )
        return {"ok": True, "confirmed": False, "reason": "cursor_home"}
    logger.warning(
        "pty_send: no prompt within 4s, retrying with Enter only: sid=%s text_len=%d slash=%s cursor_y=%s",
        session_id, len(text or ""), is_slash, cursor_y,
    )
    tmux_send_keys(session_id, enter=True)
    if await _wait_count_added(counter, jsonl_path, initial_pos, timeout=1.0):
        return {"ok": True, "confirmed": True, "retried": "enter_only"}
    logger.warning(
        "pty_send: not confirmed within window, assume delivered (no re-paste): sid=%s slash=%s",
        session_id, is_slash,
    )
    return {"ok": True, "confirmed": False}
