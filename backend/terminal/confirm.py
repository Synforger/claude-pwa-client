"""送信本文 (= text / slash command) が tmux 経由で claude に届いたかを JSONL から確認する。

`pty_routes` の endpoint (= /pty/{sid}/send, /send-with-files) から呼ばれる。 旧実装は
pty_routes.py に同居していたが、 純粋な「JSONL カウント + wait」 の責務なので分離した。

挙動:
    1. 送信直前に jsonl_path の現在 file size (= initial_pos) を取る
    2. tmux send-keys が成功したら _confirm_after_send を呼ぶ
    3. initial_pos から差分行だけ tail (= read_complete_lines) で読み、 該当 user 行が +1 されるか
       を 4s 監視 → 結果を confirmed として返すだけ (= 観測専用)

救済 Enter は退役 (= 2026-07-05): 生 PTY 直 write 時代の paste/Enter 競合対策だったが、
control mode + send-keys -H 移行後の実発生が確認できず、 一方で /model 等の picker を
開く slash command で「JSONL 確認 timeout → 救済 Enter → picker の現選択を誤確定」 の
実害が出た。 取りこぼしが再発したらこの header に発生条件を記録して対策を設計し直す。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from backend.jsonl.predicates import is_user_prompt as _is_user_prompt_pred
from backend.jsonl.tail import read_complete_lines

logger = logging.getLogger(__name__)

# 送達確認の監視窓。 これを過ぎても confirmed=False は送達失敗と限らない
# (= picker 等の対話 UI や turn 実行中の queue 送信では確認行が書かれない)。
CONFIRM_TIMEOUT_SEC: float = 4.0

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
    """送信直後の到達確認 (= text 経路 / 添付経路 共通、 観測専用)。

    initial_pos = 送信直前のファイルサイズ。 そこから新規 user 行 (slash なら
    `<command-name>`、 そうでなければ素プロンプト) が出るかを 4s 監視して confirmed を
    返す。 confirmed=False でも送達失敗とは限らない (= picker 等の対話 UI が開いてる間
    は command 完了行が書かれない)。 介入 (= 再送 / 救済キー) はしない。
    """
    counter = _count_command_lines if is_slash else _count_user_prompts
    if await _wait_count_added(
        counter, jsonl_path, initial_pos, timeout=CONFIRM_TIMEOUT_SEC
    ):
        return {"ok": True, "confirmed": True}
    logger.info(
        "pty_send: not confirmed within %.0fs (interactive UI or slow turn; "
        "no intervention): sid=%s text_len=%d slash=%s",
        CONFIRM_TIMEOUT_SEC, session_id, len(text or ""), is_slash,
    )
    return {"ok": True, "confirmed": False}
