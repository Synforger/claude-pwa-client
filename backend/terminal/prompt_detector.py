"""tmux pane が「入力待ち」 かどうかを判定する pure detector (= Phase 1)。

背景:
    ``--dangerously-skip-permissions`` 有効時でも subprocess (= sudo / ssh / apt /
    npm publish OTP / bash select 等) が発する prompt には claude は答えられず、
    ユーザが気付かないと session が沈黙する。 PWA から気付けるようにするため、
    tmux が公開する signal を poll して 4 tier で状態を判定する。

Tier 分離 (= 実測ベース、 verify script は plans/prompt-detector-verify.md):
    A. alternate_on=1 → full-screen TUI (less / vim / nano / fzf / editor)
    B. inline TUI マーカ (= ``❯`` cursor + 選択肢行 + 罫線) → Inquirer / Claude Code 自身
    C. text tail regex hit (= yn / password / OTP / bash select 等)
    D. content-hash が N 秒不変 → idle fallback

判定順序は A > B > C > D。 上位が hit したら下位は skip。

本モジュールは pure (= I/O なし)。 tmux の poll + event 発火は Phase 2 の loop で
組む。 ここは analyze() が snapshot を受けて Verdict を返す関数の集合体。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PromptState(str, Enum):
    """検出結果 (= PWA UI + Push が振り分けに使う)。"""

    ACTIVE = "active"           # 出力更新中 / 直前まで動いていた
    TUI = "tui"                 # tier A: alternate_on=1
    INLINE_TUI = "inline_tui"   # tier B: ❯ + 選択肢 + 罫線
    TEXT_PROMPT = "text_prompt"  # tier C: 具体 prompt 検出 (= yn/password/etc)
    IDLE = "idle"               # tier D: 長時間無変化、 pattern hit なし


class PromptCategory(str, Enum):
    """TEXT_PROMPT の細分類。 UI が入力欄 UX (= password mask 等) を切替るのに使う。"""

    CONFIRM_YN = "confirm_yn"          # [Y/n] / (y/n) / (yes/no)
    PASSWORD = "password"              # Password: / Passphrase: (mask on)
    OTP = "otp"                        # Enter OTP: / one-time password:
    HASH_CHOICE = "hash_choice"        # bash select `#? `
    NUMBERED_MENU = "numbered_menu"    # 1) foo\n2) bar 系
    GENERIC_QUESTION = "generic_question"  # ? or : 末尾 fallback


# --- Tier C regex ------------------------------------------------------------
#
# 実測 (= verify script) で 12 の実 prompt パターンに対して検証済。
# 全 pattern は tail の**末尾**を見る (= 会話 log 内の [Y/n] を hit させない)。

_YN_BRACKET_RE = re.compile(r"\[[YyNn]/[YyNn]\]\s*$")
_YN_PAREN_RE = re.compile(r"\(yes/no[^)]*\)\s*[?:]?\s*$|\([Yy]/[Nn]\)\s*[?:]?\s*$")
_PASSWORD_RE = re.compile(
    r"([Pp]assword|[Pp]assphrase|\bpasswd\b)[^\n:]*:\s*$"
)
_OTP_RE = re.compile(
    r"(OTP|one[- ]time[- ]password|verification code|2FA code)[^\n:]*:\s*$",
    re.IGNORECASE,
)
_HASH_CHOICE_RE = re.compile(r"^#\?\s*$", re.MULTILINE)
_NUMBERED_MENU_RE = re.compile(
    # 2 行以上の "N) foo" / "N. foo" が近接して出ていれば選択肢メニュー
    r"(?m)^\s*[0-9]+[.)]\s+\S.*(?:\r?\n\s*[0-9]+[.)]\s+\S.*){1,}"
)
_GENERIC_Q_TAIL_RE = re.compile(r"[?:>]\s*$")

# Tier B (= inline TUI)。 Claude Code の feedback dialog は「dialog 表示 + 空の
# 入力欄 `❯ `」 なので arrow 行に \S を要求しない (= bare `❯ ` も match)。
# 「typed text しかない場合」 の tier B false positive は、 「近傍 3 行に numbered
# option があるか」 の後段判定で弾く (= arrow 単独では inline_tui にしない設計)。
_ARROW_CURSOR_RE = re.compile(r"^\s*[❯▶➜→](\s|$)", re.MULTILINE)
_BOX_DRAWING_RE = re.compile(r"[╭╮╰╯┌┐└┘├┤┬┴┼─│]")
# ANSI cursor-up (= redraw 系 TUI の signature、 pty tail に残らないので escape ありの
# capture-pane -e で拾う。 現在は使わない: capture 側で -e 付けない設計)
# _CURSOR_UP_RE = re.compile(r"\x1b\[\d*A")

# Claude Code 自身の bypass mode chip (= bottom status line)。 これは prompt 判定でなく
# 「bypass 中」 の UI 表示に流す情報として抜き出す。
_BYPASS_CHIP_RE = re.compile(r"⏵⏵\s*bypass permissions on")


@dataclass(frozen=True)
class TailSnapshot:
    """1 回の tmux poll で撮る状態。 detector はこれと前回 snapshot だけを見る。"""

    alternate_on: bool
    # 末尾 N 行の plain text (= tmux capture-pane -p、 escape なし)。 hash と regex に使う。
    tail_text: str
    # 監視時刻 (= 単調時刻、 loop.time() など)。 idle 判定に使う。
    now_sec: float

    @property
    def tail_hash(self) -> str:
        return hashlib.md5(self.tail_text.encode("utf-8", errors="replace")).hexdigest()

    @property
    def bypass_mode_visible(self) -> bool:
        return bool(_BYPASS_CHIP_RE.search(self.tail_text))


@dataclass
class DetectorConfig:
    """closure 変数を集約 (= 後から user 設定に差し替え可能)。"""

    idle_threshold_sec: float = 2.0    # tier C の「idle かつ pattern」 の idle 要件
    long_idle_threshold_sec: float = 5.0  # tier D の「長期沈黙」 閾値
    # 入力送信直後の grace period (= ユーザ入力を pattern hit と誤検知しない)
    post_input_grace_sec: float = 1.5


@dataclass
class Verdict:
    """analyze() の返り値。 event 発火 / UI 更新の元ネタ。"""

    state: PromptState
    category: Optional[PromptCategory] = None
    # UI に出す「入力待ちの原文抜粋」 (= 末尾 1-3 行、 空白 trim)
    excerpt: str = ""
    bypass_mode_visible: bool = False
    # 判定根拠 (= debug / log 用)
    reason: str = ""


@dataclass
class DetectorState:
    """poll loop 側が持つ「前回」 の記憶。 stateful (= mutable)。"""

    last_snapshot: Optional[TailSnapshot] = None
    # tail_hash → その hash が最初に観測された時刻。 hash が変わったら reset。
    hash_first_seen_at: float = 0.0
    hash_cached: str = ""
    # ユーザが tmux に input を送った最終時刻 (= caller が record_input_sent で更新)。
    last_input_sent_at: float = 0.0
    # 現在の state (= transition 判定用、 一度出した prompt を連発しない)
    current_state: PromptState = PromptState.ACTIVE
    # 初回 tick 判定用。 True になるまでは 「ACTIVE → observed state」 の遷移を
    # 通常の transition として扱わない (= backend restart 直後に全 session ぶんの
    # push が一斉発火するのを防ぐ)。 loop 側で「初回 tick で観測した state を
    # 追認する」 ハンドリングに使う。
    seeded: bool = False

    def record_input_sent(self, now_sec: float) -> None:
        self.last_input_sent_at = now_sec

    def _refresh_hash(self, snapshot: TailSnapshot) -> None:
        h = snapshot.tail_hash
        if h != self.hash_cached:
            self.hash_cached = h
            self.hash_first_seen_at = snapshot.now_sec
        # 同 hash なら hash_first_seen_at は据え置き (= 出力停止時刻の起点)

    def _idle_for(self, snapshot: TailSnapshot) -> float:
        return max(0.0, snapshot.now_sec - self.hash_first_seen_at)

    def _seconds_since_input(self, snapshot: TailSnapshot) -> float:
        return max(0.0, snapshot.now_sec - self.last_input_sent_at)


# --- Tier 判定 (= 各 tier は独立関数、 上位で早期 return) --------------------


def _tier_a_alternate(snapshot: TailSnapshot) -> Optional[Verdict]:
    if snapshot.alternate_on:
        return Verdict(
            state=PromptState.TUI,
            excerpt="",  # 全画面 TUI は text 抽出しない (= redraw が激しく意味を成さない)
            bypass_mode_visible=snapshot.bypass_mode_visible,
            reason="alternate_on=1",
        )
    return None


def _tier_b_inline_tui(snapshot: TailSnapshot) -> Optional[Verdict]:
    """inline TUI 選択 dialog を検出。

    実運用 hotfix: 「❯ + 罫線」 は Claude Code の通常入力画面 (= 素の input prompt +
    horizontal rule 群 + bottom status bar の box drawing) にも当てはまるため、
    single sig で inline_tui を出すと **Claude Code 起動中の全 session が push を吐く**
    誤検知になる (= 2026-07-05 実測)。 判定は 「❯ 行の**近傍 3 行以内** に numbered
    option が同居する」 という「実際に選択肢がある」 signature に絞る:

        ❯ 1. Yes, I trust this folder
          2. No, exit

    もしくは:

        Select an option:
        ❯ development
          staging
          production

    ❯ + 番号列挙 のペアが取れない (= 単独 `❯` 入力欄 / 通常会話) は tier B に落とさず
    tier C / D に流す。
    """
    tail = snapshot.tail_text
    lines = tail.splitlines()
    # 縦並び 1 行 signature (= `❯ 1. Yes` / `1) foo` / `1: Bad`)。 `:` は Claude Code
    # の feedback dialog (= `1: Bad  2: Fine  3: Good  0: Dismiss`) 対応で追加。
    stacked_option_re = re.compile(r"^\s*[❯▶➜→]?\s*[0-9]+[.):]\s+\S")
    # 横並び 1 行 signature (= 同一行に「N: text」 が 2+ 出る、 上の feedback dialog は
    # 4 option 横並びなので stacked では拾えない)。
    inline_options_re = re.compile(r"(?:\s|^)[0-9]+:\s+\S.*?(?:\s|^)[0-9]+:\s+\S")
    for i, ln in enumerate(lines):
        if not _ARROW_CURSOR_RE.match(ln):
            continue
        window = lines[max(0, i - 3): i + 4]
        # window 内で option signature を探す (= stacked も inline も 1 hit で成立)
        numbered_hits = sum(
            1 for w in window
            if stacked_option_re.match(w) or inline_options_re.search(w)
        )
        if numbered_hits >= 1:
            return Verdict(
                state=PromptState.INLINE_TUI,
                excerpt=_extract_arrow_menu_excerpt(tail),
                bypass_mode_visible=snapshot.bypass_mode_visible,
                reason="arrow+numbered_option",
            )
    return None


def _tier_c_text_prompt(
    snapshot: TailSnapshot, state: DetectorState, config: DetectorConfig
) -> Optional[Verdict]:
    # ユーザが直近 input 送った直後は誤検知 (= 送信 char が末尾に見えている) を避ける
    if state._seconds_since_input(snapshot) < config.post_input_grace_sec:
        return None
    # idle が閾値未満なら「まだ出力中の可能性」 として skip
    if state._idle_for(snapshot) < config.idle_threshold_sec:
        return None
    tail = snapshot.tail_text
    for pattern, category in (
        # 順序: 具体度の高いものを先に (= OTP は "password" を含みうるが OTP と扱いたい)。
        (_OTP_RE, PromptCategory.OTP),
        (_YN_BRACKET_RE, PromptCategory.CONFIRM_YN),
        (_YN_PAREN_RE, PromptCategory.CONFIRM_YN),
        (_PASSWORD_RE, PromptCategory.PASSWORD),
        (_HASH_CHOICE_RE, PromptCategory.HASH_CHOICE),
        (_NUMBERED_MENU_RE, PromptCategory.NUMBERED_MENU),
    ):
        if pattern.search(tail):
            return Verdict(
                state=PromptState.TEXT_PROMPT,
                category=category,
                excerpt=_extract_prompt_excerpt(tail),
                bypass_mode_visible=snapshot.bypass_mode_visible,
                reason=f"regex:{category.value}",
            )
    # generic fallback: 末尾が ? or : (= 未知の質問形)
    if _GENERIC_Q_TAIL_RE.search(tail):
        return Verdict(
            state=PromptState.TEXT_PROMPT,
            category=PromptCategory.GENERIC_QUESTION,
            excerpt=_extract_prompt_excerpt(tail),
            bypass_mode_visible=snapshot.bypass_mode_visible,
            reason="generic_q_tail",
        )
    return None


def _tier_d_idle(
    snapshot: TailSnapshot, state: DetectorState, config: DetectorConfig
) -> Optional[Verdict]:
    if state._idle_for(snapshot) >= config.long_idle_threshold_sec:
        return Verdict(
            state=PromptState.IDLE,
            excerpt="",
            bypass_mode_visible=snapshot.bypass_mode_visible,
            reason=f"idle>={config.long_idle_threshold_sec}s",
        )
    return None


def _extract_arrow_menu_excerpt(tail: str) -> str:
    """❯ の周辺 3 行を抜粋 (= 選択肢 UI で目立たせる)。"""
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if _ARROW_CURSOR_RE.match(ln):
            start = max(0, i - 1)
            return "\n".join(lines[start : i + 3]).strip()
    return "\n".join(lines[-4:]).strip()


def _extract_prompt_excerpt(tail: str) -> str:
    """text prompt の末尾 2 行を抜粋 (= sudo / ssh 等の 1-2 行 prompt を余分な文脈なしで)。"""
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-2:]).strip()


# --- 公開 API ---------------------------------------------------------------


def analyze(
    snapshot: TailSnapshot,
    state: DetectorState,
    config: Optional[DetectorConfig] = None,
) -> Verdict:
    """poll loop から毎回呼ぶ主判定。 state を副作用で更新する。

    呼び出し側の使い方:
        state = DetectorState()
        config = DetectorConfig()
        while True:
            snap = poll_tmux(...)
            verdict = analyze(snap, state, config)
            if verdict.state != state.current_state:
                emit_event(verdict)
                state.current_state = verdict.state
            await asyncio.sleep(0.5)

    ユーザが input を送った直後は record_input_sent(now) を呼んでもらう
    (= grace period に反映)。
    """
    cfg = config or DetectorConfig()
    state._refresh_hash(snapshot)

    for tier in (
        lambda: _tier_a_alternate(snapshot),
        lambda: _tier_b_inline_tui(snapshot),
        lambda: _tier_c_text_prompt(snapshot, state, cfg),
        lambda: _tier_d_idle(snapshot, state, cfg),
    ):
        verdict = tier()
        if verdict is not None:
            state.last_snapshot = snapshot
            return verdict

    state.last_snapshot = snapshot
    return Verdict(
        state=PromptState.ACTIVE,
        bypass_mode_visible=snapshot.bypass_mode_visible,
        reason="no_tier_hit",
    )
