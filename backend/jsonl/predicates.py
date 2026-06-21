"""JSONL 1 行の性質を判定する純粋 predicate 集約 (= backend-F-05)。

同じ判定が session_status.py / events.py / terminal/confirm.py で**それぞれ別実装**で
重複していた問題 (= `is_user_prompt` vs `_is_plain_user_prompt` の 2 経路、 判定がズレると
busy / unread / count が静かに食い違う) を 1 module に集約する。

純粋関数のみ、 backend state には触らない。 1 行 dict (= json.loads 済) を受け取って
bool を返すだけなので test も fixture 不要。
"""
from __future__ import annotations

from backend.jsonl.events import HARNESS_XML_RE, INTERRUPT_USER_RE


def is_sidechain(line: dict) -> bool:
    """サブエージェント (= Task で起動した子 agent) の行か。 親 chat には混ぜない。"""
    return bool(line.get("isSidechain"))


def is_meta(line: dict) -> bool:
    """harness が注入するメタメッセージ (= caveat / malformed retry 指示等)。 chat 非表示。"""
    return bool(line.get("isMeta"))


def is_harness_xml_text(text: str) -> bool:
    """claude TUI が user 行として書く harness 内部表現 (= `<command-name>` 等 + interrupt
    marker `[Request interrupted by user]`) か。 該当ならユーザ発話扱いしない。"""
    if not isinstance(text, str):
        return False
    s = text.strip()
    if not s:
        return False
    return bool(HARNESS_XML_RE.match(s) or INTERRUPT_USER_RE.match(s))


def is_user_prompt(line: dict) -> bool:
    """素プロンプト (= 実ユーザ発言の user 行) か。 tool_result の user 行 / isMeta /
    isSidechain は除外する。 harness XML / interrupt marker も除外する
    (= 旧 session_status.is_user_prompt と同じ semantics、 こちらが正本)。

    `[Request interrupted by user]` は claude が中断完了を marker として user 行に書く
    もので、 新プロンプトではない (2026-06-04 真因)。 ユーザ発話扱いすると busy=True が
    再点火し、 終端 stop_reason 行が来ないため停止ボタンが送信ボタンに戻らなくなる。

    `<command-name>/clear</command-name>` 等の slash command / shell stdout も同じ理由で除外
    (2026-05-31 修正)。
    """
    if line.get("type") != "user" or is_sidechain(line) or is_meta(line):
        return False
    content = (line.get("message") or {}).get("content")
    if isinstance(content, str):
        s = content.strip()
        if not s:
            return False
        if is_harness_xml_text(s):
            return False
        return True
    if isinstance(content, list):
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "text":
                continue
            t = (b.get("text") or "").strip()
            if not t:
                continue
            if is_harness_xml_text(t):
                continue
            return True
        return False
    return False
