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

# Claude Code の bottom status bar (= rate-limit / spinner) は idle 中でも中身が
# 動く (= `5h:60%(1h49m)` の分カウントダウン、 `Razzmatazzing… (1m 26s)` の経過秒)。
# idle hash にこれを含めると「入力待ちでじっとしてる」 のに hash が毎秒変わって idle
# 判定が壊れる。 hash 前にこの手の volatile 行を落とす。
_VOLATILE_STATUS_RE = re.compile(
    r"5h:\s*\d+%"                 # rate-limit bar (= 分カウントダウンを含む)
    r"|7d:\s*\d+%"               # 7d rate-limit
    r"|…\s*\(\d+"                # spinner の経過秒 `… (1m 26s)` / `… (47s`
    r"|·\s*↓\s*[\d.]+k?\s*tokens"  # token counter
)


def _strip_volatile_lines(text: str) -> str:
    """idle hash 用に status bar / spinner の変動行を除去する。"""
    return "\n".join(
        ln for ln in text.splitlines() if not _VOLATILE_STATUS_RE.search(ln)
    )


@dataclass(frozen=True)
class TailSnapshot:
    """1 回の tmux poll で撮る状態。 detector はこれと前回 snapshot だけを見る。"""

    alternate_on: bool
    # 末尾 N 行の plain text (= tmux capture-pane -p、 escape なし)。 regex 判定に使う。
    tail_text: str
    # 監視時刻 (= 単調時刻、 loop.time() など)。 idle 判定に使う。
    now_sec: float

    @property
    def tail_hash(self) -> str:
        # volatile 行 (= rate-limit / spinner) を除いてから hash (= idle 判定が
        # 分カウントダウン / 経過秒で誤 reset しないように)。
        basis = _strip_volatile_lines(self.tail_text)
        return hashlib.md5(basis.encode("utf-8", errors="replace")).hexdigest()

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


class InputMode(str, Enum):
    """PWA が表示する quick-reply UI の種別。

    numbers: 数字ボタン群 (= Ink 系 dialog は 1 打鍵で即決定、 bash select は Enter 必要)
    yn:      Y/n ボタン (= confirm_yn 系、 Enter 必要)
    arrows:  ↑/↓/Enter ボタン (= 番号無し picker、 Phase 4b で実装)
    none:    quick reply UI 出さない (= password / otp / 未分類 idle)
    """

    NUMBERS = "numbers"
    YN = "yn"
    ARROWS = "arrows"
    NONE = "none"


# excerpt から数字 option を抽出する regex。 縦並び 1 行 (`❯ 1. Yes` / `1) foo` / `1: Bad`)
# と 横並び 1 行 (`1: Bad  2: Fine  3: Good  0: Dismiss`) の両方に対応。 抽出は「行頭または
# 空白から始まる 1-2 桁数字 + . / ) / : + space + non-space」 で個々の option 数字を集める。
_OPTION_DIGIT_RE = re.compile(r"(?:^|\s)([0-9]{1,2})[.):]\s+\S")


def _text_category_to_input_mode(
    category: PromptCategory, source: str
) -> tuple["InputMode", list[str]]:
    """text prompt の category を PWA button UI 用 (input_mode, options) に翻訳。

    - CONFIRM_YN → yn button 2 個
    - HASH_CHOICE / NUMBERED_MENU → source (= full tail) から option 数字を抽出
      (excerpt は末尾 2 行だけなので numbered_menu の全 option を拾えない)
    - PASSWORD / OTP / GENERIC_QUESTION → button なし (= 手入力)
    """
    if category == PromptCategory.CONFIRM_YN:
        return (InputMode.YN, ["Y", "n"])
    if category in (PromptCategory.HASH_CHOICE, PromptCategory.NUMBERED_MENU):
        digits = _extract_option_digits(source)
        return (InputMode.NUMBERS, digits) if digits else (InputMode.NONE, [])
    return (InputMode.NONE, [])


def _extract_option_digits(excerpt: str) -> list[str]:
    """excerpt 内の数字 option (`1: Bad` / `❯ 1. Yes` 等) を順序保持で抽出。 重複除去。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in _OPTION_DIGIT_RE.finditer(excerpt):
        d = m.group(1)
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


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
    # quick-reply UI の種別 (= PWA 側の button 群切替に使う)
    input_mode: InputMode = InputMode.NONE
    # numbers mode 時の option digit list (= `["1", "2", "3", "0"]` 等、 順序保持)
    options: list[str] = field(default_factory=list)
    # numbers / yn 時に PWA が tmux に送るキーに Enter を伴わせるか。
    # Ink dialog は不要 (= 1 打鍵で決定)、 shell prompt (= yn / bash select) は必要。
    key_requires_enter: bool = False


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
    # 直近 publish で載せた excerpt。 Phase 4b (arrow picker) は state は inline_tui で
    # 据え置きだが「❯ が移動して excerpt 中身が変わる」 のを live 反映したいので、
    # 同 state でも excerpt が変わったら追加 publish する (= push は firing しない)。
    last_excerpt: str = ""

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


# tier B の option 行 signature。
# 縦並び 1 行 (= `❯ 1. Yes` / `1) foo` / `1: Bad`)。 `:` は Claude Code の feedback
# dialog (= `1: Bad  2: Fine  3: Good  0: Dismiss`) 対応で追加。
_STACKED_OPTION_RE = re.compile(r"^\s*[❯▶➜→]?\s*[0-9]+[.):]\s+\S")
# 横並び 1 行 (= 同一行に「N: text」 が 2+ 出る、 上の feedback dialog は 4 option
# 横並びなので stacked では拾えない)。
_INLINE_OPTIONS_RE = re.compile(r"(?:\s|^)[0-9]+:\s+\S.*?(?:\s|^)[0-9]+:\s+\S")
# option 行の先頭番号 (= run 分割用)。
_OPTION_LEADING_DIGIT_RE = re.compile(r"^\s*[❯▶➜→]?\s*([0-9]+)[.):]")


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

    処理は 4 段 (= fix が入る時にどの段の話か diff で判別できる粒度):
        1. `_tier_b_candidates`     — arrow 行 / option 行の index 収集
        2. `_tier_b_clusterize`     — option 行の gap ベース cluster 化
        3. `_tier_b_select_picker`  — picker cluster 選定 + 番号 run 分割 + anchor 確定
        4. `_tier_b_build_verdict`  — excerpt / digits 抽出 + Verdict 構築
    """
    lines = snapshot.tail_text.splitlines()
    found = _tier_b_candidates(lines)
    if found is None:
        return None
    arrow_idx, all_opt = found
    clusters = _tier_b_clusterize(all_opt)
    picked = _tier_b_select_picker(lines, clusters, arrow_idx, all_opt)
    if picked is None:
        return None
    picker, anchor = picked
    return _tier_b_build_verdict(snapshot, lines, picker, anchor)


def _tier_b_candidates(lines: list[str]) -> Optional[tuple[list[int], list[int]]]:
    """arrow 行 index と option 行 index を収集。 どちらか欠けたら tier B 不成立。"""
    arrow_idx = [j for j, w in enumerate(lines) if _ARROW_CURSOR_RE.match(w)]
    if not arrow_idx:
        return None
    all_opt = [
        j for j, w in enumerate(lines)
        if _STACKED_OPTION_RE.match(w) or _INLINE_OPTIONS_RE.search(w)
    ]
    if not all_opt:
        return None
    return arrow_idx, all_opt


def _tier_b_clusterize(all_opt: list[int]) -> list[list[int]]:
    """option 行を gap<=6 で cluster 化する。

    「最も option 数が多い」 塊を picker 本体とみなす前段 (= /model は 5 option、
    scrollback 内の会話 log 番号リストは 1-2 個)。 これで「先に現れた ❯ /model echo 行
    + 直上の会話番号リスト」 を picker と誤認する事象を防ぐ (= 2026-07-06 実測、 logic
    を arrow-first から cluster-first へ反転)。 gap 閾値 6: 実 /model は 1 option 4 行
    折返しで option 行間隔 ~5、 6 で塊を保つ。
    """
    clusters: list[list[int]] = [[all_opt[0]]]
    for idx in all_opt[1:]:
        if idx - clusters[-1][-1] <= 6:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])
    return clusters


def _tier_b_select_picker(
    lines: list[str],
    clusters: list[list[int]],
    arrow_idx: list[int],
    all_opt: list[int],
) -> Optional[tuple[list[int], int]]:
    """picker cluster の選定 + 番号 run 分割 + anchor (= cursor 行) 確定。

    picker 本体の選び方 (= 会話 log の番号リスト / ❯ /model echo との分離):
    選択カーソルが option 行に乗る picker (= /model, trust dialog) は `❯ 3. Fable` が
    arrow かつ option。 その arrow-option を含む cluster を優先採用する。 gap 併合で
    会話リストと 1 塊になっても、 後段の run 分割で会話側を切り落とす。
    """
    arrow_set = set(arrow_idx)
    picker = next((c for c in clusters if any(j in arrow_set for j in c)), None)
    if picker is None:
        # カーソルが option 行に乗らない dialog (= feedback の bare `❯ `) は、 bare arrow
        # の直近 (±2) に端がある cluster を採る。 複数あれば option 数最多。
        candidates = [
            c for c in clusters
            if min(abs(c[0] - a) for a in arrow_idx) <= 2
            or min(abs(c[-1] - a) for a in arrow_idx) <= 2
        ]
        if not candidates:
            return None
        picker = max(candidates, key=len)

    # anchor = カーソル。 option 行に乗る arrow (= `❯ 3. Fable`) を最優先 (= echo arrow
    # `❯ /model` を掴んで excerpt 起点が上にずれるのを防ぐ)。 無ければ picker 近傍の arrow。
    opt_set = set(all_opt)
    anchor = next(
        (a for a in arrow_idx if a in opt_set and picker[0] - 2 <= a <= picker[-1] + 2),
        next((a for a in arrow_idx if picker[0] - 2 <= a <= picker[-1] + 2), picker[0]),
    )

    # gap 併合で会話リストが混ざった場合の最終分離 (= 2026-07-06): picker の option 番号
    # は単調増加 (1,2,3,4,5)。 会話 `1,2` + picker `1,2,3,4,5` が併合すると番号列は
    # 1,2,1,2,3,4,5 で「2→1 の減少」 が境界になる。 番号が増加し続ける run に分割し、
    # anchor を含む run だけ残す。
    runs: list[list[int]] = []
    cur: list[int] = []
    last_d = None
    for j in picker:
        m = _OPTION_LEADING_DIGIT_RE.match(lines[j])
        d = int(m.group(1)) if m else None
        if d is None:
            # inline 横並び (= feedback dialog 1 行に複数)。 分割しない、 現 run に足す。
            cur.append(j)
            continue
        if last_d is not None and d <= last_d:
            runs.append(cur)
            cur = []
        cur.append(j)
        last_d = d
    if cur:
        runs.append(cur)
    picker = next((r for r in runs if anchor in r or (r and r[0] <= anchor <= r[-1])), picker)
    if not picker:
        return None

    # anchor を最終 run 内の arrow (= cursor) に取り直す (= 分割前の echo arrow を掴んで
    # excerpt 起点が上にずれるのを防ぐ)。 run 内に arrow が無ければ run 先頭。
    anchor = next((a for a in arrow_idx if picker[0] <= a <= picker[-1]), picker[0])
    return picker, anchor


def _tier_b_build_verdict(
    snapshot: TailSnapshot,
    lines: list[str],
    picker: list[int],
    anchor: int,
) -> Verdict:
    """picker 範囲から excerpt / option digits を抽出して Verdict を組む。"""
    lo = max(0, min(picker[0], anchor) - 2)
    hi = min(len(lines), max(picker[-1], anchor) + 5)
    block = lines[lo:hi]
    block_text = "\n".join(w for w in block if w.strip()).strip()
    digits = _extract_option_digits(block_text)
    return Verdict(
        state=PromptState.INLINE_TUI,
        excerpt=block_text,
        bypass_mode_visible=snapshot.bypass_mode_visible,
        reason="arrow+numbered_option",
        # Ink dialog は 1 打鍵で即決定、 Enter 不要
        input_mode=InputMode.NUMBERS if digits else InputMode.ARROWS,
        options=digits,
        key_requires_enter=False,
    )


def _claude_tui_owns_screen(tail: str) -> bool:
    """pane 末尾が Claude Code 自身の TUI (= 入力欄 + status bar) かを判定。

    末尾 4 行に rate-limit status (`5h:NN%`) か bypass chip が見えていれば Claude TUI
    が画面を占有中。 この状態で subprocess の生 prompt が pane 末尾に居ることは構造上
    ありえない (= subprocess 出力は Claude が tool 経由で吸収して会話 log に描画する)
    ので、 tier C は skip してよい。 逆に subprocess が真に画面を持ってる時 (= claude
    未起動の生 shell 等) は status bar が無いので tier C が生きる。

    Why: チャット本文に含まれる番号リスト / `[Y/n]` 例文が pane に描画されて tier C
    の regex に誤 hit する class の誤検知 (= 2026-07-06 実測) を構造的に塞ぐ。
    """
    last_lines = tail.splitlines()[-4:]
    for ln in last_lines:
        if _VOLATILE_STATUS_RE.search(ln) or _BYPASS_CHIP_RE.search(ln):
            return True
    return False


def _tier_c_text_prompt(
    snapshot: TailSnapshot, state: DetectorState, config: DetectorConfig
) -> Optional[Verdict]:
    # ユーザが直近 input 送った直後は誤検知 (= 送信 char が末尾に見えている) を避ける
    if state._seconds_since_input(snapshot) < config.post_input_grace_sec:
        return None
    # idle が閾値未満なら「まだ出力中の可能性」 として skip
    if state._idle_for(snapshot) < config.idle_threshold_sec:
        return None
    # Claude TUI が画面を占有中なら text prompt は存在しえない (= dialog は tier B が担当)
    if _claude_tui_owns_screen(snapshot.tail_text):
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
            excerpt = _extract_prompt_excerpt(tail)
            # option 抽出は full tail から (= excerpt は 2 行なので numbered_menu の全部を拾えない)
            input_mode, options = _text_category_to_input_mode(category, tail)
            return Verdict(
                state=PromptState.TEXT_PROMPT,
                category=category,
                excerpt=excerpt,
                bypass_mode_visible=snapshot.bypass_mode_visible,
                reason=f"regex:{category.value}",
                input_mode=input_mode,
                options=options,
                # shell prompt は 1 打鍵で確定しない、 Enter を要する
                key_requires_enter=input_mode in (InputMode.YN, InputMode.NUMBERS),
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
