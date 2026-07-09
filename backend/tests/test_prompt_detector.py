"""prompt_detector の pure 判定を実測パターンで verify する。

verify script (= 実 tmux / 実 CLI) で観測した 12+ の prompt tail を fixture 化し、
tier A / B / C / D が期待通りに hit するかを確認する。
"""
from __future__ import annotations

import pytest

from backend.terminal.prompt_detector import (
    DetectorConfig,
    DetectorState,
    InputMode,
    PromptCategory,
    PromptState,
    TailSnapshot,
    analyze,
)


def _snap(tail: str, *, alternate: bool = False, now: float = 100.0) -> TailSnapshot:
    return TailSnapshot(alternate_on=alternate, tail_text=tail, now_sec=now)


def _prime_state(tail: str, idle_since: float = 0.0) -> DetectorState:
    """analyze() が hash を確定 → idle 起点時刻を過去に固定するためのお膳立て helper。

    analyze() は「観測された hash が変わったら first_seen をリセット」 する。 テストで
    「idle が閾値を超えた状態」 を作るには、 一度その内容で観測させた **後で** first_seen
    だけ過去にずらす。 hash_cached を hand-set しても内容と一致しなければ次呼びでリセット
    されるので、 実際の hash を使う。
    """
    from backend.terminal.prompt_detector import TailSnapshot

    s = DetectorState()
    # 事前観測: hash_cached を実 hash に置く (= 次の analyze で reset されない)
    seed = TailSnapshot(alternate_on=False, tail_text=tail, now_sec=idle_since)
    s.hash_cached = seed.tail_hash
    s.hash_first_seen_at = idle_since
    return s


def _new_state() -> DetectorState:
    """まだ何も観測してない生 state。 idle_since 不要 tier (= A/B/bypass) 用。"""
    return DetectorState()


# ---------------------------------------------------------------------------
# Tier A: alternate screen
# ---------------------------------------------------------------------------


def test_tier_a_alternate_wins_over_everything():
    tail = "❯ 1. Yes, allow all\n  2. No\n[Y/n] "  # 全 tier hit しうる内容
    verdict = analyze(_snap(tail, alternate=True), _new_state())
    assert verdict.state == PromptState.TUI
    assert verdict.reason == "alternate_on=1"


def test_tier_a_off_falls_through():
    verdict = analyze(_snap("hello", alternate=False), _new_state())
    assert verdict.state == PromptState.ACTIVE


def test_tier_a_skipped_when_claude_tui_owns_screen():
    """claude 2.1.201 実測 (= 2026-07-06): alternate flag が立ったまま Claude TUI 本体が
    画面に居る pane がある。 可視内容が Claude TUI (= status bar 末尾) なら tier A を
    出さない (= 「TUI running」 banner の常時点灯誤検知を塞ぐ)。"""
    tail = "some conversation output\n❯ \n  [Opus 4.7] 5h:83%(4h16m) 7d:13% ctx:15%"
    verdict = analyze(_snap(tail, alternate=True), _new_state())
    assert verdict.state != PromptState.TUI


def test_tier_a_skipped_for_short_form_status_bar():
    """起動直後の短縮形 status bar (= rate-limit 未載、 `[Opus 4.7] ctx:░░0%` だけ) でも
    Claude TUI と認識して tier A を skip する (= 2026-07-06 会社 PC 実測、 welcome banner
    表示中の pane 3 本が alternate flag 立ちのままこの形で常時 TUI 誤検知)。"""
    tail = "▎ Fable 5 is back.\n────────\n❯ \n────────\n[Opus 4.7] ctx:░░░░░░░░0%\n← for agents"
    verdict = analyze(_snap(tail, alternate=True), _new_state())
    assert verdict.state != PromptState.TUI


def test_tier_a_still_fires_for_real_fullscreen_tui():
    """vim / less 等 (= status bar 無し) は alternate flag で従来通り TUI 検出。"""
    tail = "~\n~\n~\n:q to quit"
    verdict = analyze(_snap(tail, alternate=True), _new_state())
    assert verdict.state == PromptState.TUI
    assert verdict.reason == "alternate_on=1"


# ---------------------------------------------------------------------------
# Tier B: inline TUI (❯ + 罫線 / ❯ 単独)
# ---------------------------------------------------------------------------


def test_tier_b_claude_code_trust_folder():
    """実測: Claude Code の trust folder prompt (= ❯ + 番号 option)。"""
    tail = (
        "────────────────────────────────────────────────\n"
        " ❯ 1. Yes, I trust this folder\n"
        "   2. No, exit\n"
        "────────────────────────────────────────────────"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert "1. Yes, I trust this folder" in verdict.excerpt


def test_tier_b_inquirer_numbered_list():
    """Inquirer 系 list prompt (= ❯ が付いた option + 他 option 群、 番号は付かない
    が代わりに「? 質問」 が上にある形もある)。 番号必須の regex を回避する形の
    Inquirer は tier B に落ちない (= tier C の generic_q_tail に流れる)。 我々は
    「番号 option が近傍にある」 signature に絞って false positive を潰す方針。"""
    tail = (
        "? Which environment:\n"
        "❯ 1) development\n"
        "  2) staging\n"
        "  3) production"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert "1) development" in verdict.excerpt


def test_tier_b_no_arrow_no_hit():
    """罫線 (= ─) だけの chat 出力 (= region separator) を inline TUI にしない。"""
    tail = "some output\n────────\nmore output"
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.ACTIVE


def test_tier_b_picker_ignores_chat_numbered_list_above():
    """実測 (= 2026-07-06): scrollback を含めると picker の上の会話 log にある番号
    リスト (= assistant の「1. ... 2. ...」) まで excerpt / options に混入していた。
    cluster-first で「最多 option の塊 = picker 本体」 を選び、 会話文と ❯ /model echo
    を除外する。"""
    tail = (
        "救済は復活させない。 理由:\n"
        "  1. queue でした\n"
        "  2. 区別できない構造欠陥\n"
        "代わりに予防を完成。\n"
        "❯ /model\n"
        "──────────────────────────────\n"
        "  Select model\n"
        "    1. Default    Opus 4.8\n"
        "    2. Opus       Opus 4.8\n"
        "  ❯ 3. Fable ✔   Fable 5\n"
        "    4. Sonnet     Sonnet 5\n"
        "    5. Haiku      Haiku 4.5\n"
        "  Enter to set as default"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert verdict.options == ["1", "2", "3", "4", "5"]
    assert "救済" not in verdict.excerpt  # 会話文が混入しない
    assert "1. Default" in verdict.excerpt


def test_tier_b_numbered_list_without_arrow_nearby_is_not_inline_tui():
    """近傍に ❯ が無い番号リスト (= docs / 会話の箇条書き) は picker でない。"""
    tail = (
        "手順:\n"
        "  1. clone する\n"
        "  2. install する\n"
        "  3. run する\n"
        "以上です。\n"
        "普通の文が続く。"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state != PromptState.INLINE_TUI


def test_tier_b_bare_arrow_without_numbered_option_is_not_inline_tui():
    """実測 hotfix: Claude Code の通常入力画面 (= ❯ 単独 + 罫線 + status bar) を
    inline TUI にしない (= 2026-07-05 backend restart 時に全 session ぶんの push が
    発火した現象への対処)。 番号 option が近傍にないなら tier B は素通り。"""
    tail = (
        "─────────────────────────────────────────────────\n"
        "❯ \n"
        "─────────────────────────────────────────────────\n"
        "[Opus 4.7] 5h:83%(4h16m) 7d:13% ctx:15%"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state != PromptState.INLINE_TUI


def test_tier_b_claude_code_feedback_dialog():
    """実測: Claude Code の feedback dialog (= `1: Bad  2: Fine  3: Good  0: Dismiss`
    が 1 行に横並び、 colon 区切り)。 前 hotfix (= v0.2.2) では colon + 横並びを
    拾えず、 session がずっと feedback 待ちで chip が出ない状態だった (= 実 pane
    dump で発覚)。"""
    tail = (
        "● How is Claude doing this session? (optional)\n"
        "  1: Bad    2: Fine   3: Good   0: Dismiss\n"
        "──────────────────────────────────────────────────\n"
        "❯ "
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI, (
        f"expected INLINE_TUI, got {verdict.state} ({verdict.reason})"
    )


def test_tier_b_stacked_colon_format():
    """N: text の縦並びも拾う (= 一部 CLI が使う書式)。"""
    tail = "Choose:\n❯ 1: alpha\n  2: beta\n  3: gamma"
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI


def test_tier_b_tall_model_picker_full_options():
    """実測 (= /model picker dump): 選択肢が 3 行折返しで縦に広がり、 pane には ❯ が
    2 個 (= コマンド echo `❯ /model` と picker cursor `❯ 3. Fable`) 出る。 picker の
    ❯ を選び、 全 5 option を拾えること。 8 行 tail では ❯ に届かず取り逃していた
    (= 2026-07-05、 capture を 40 行に拡張して解決)。"""
    tail = (
        "❯ /model\n"
        "──────────────────────────────────────\n"
        "  Select model\n"
        "  Switch between Claude models.\n"
        "\n"
        "    1. Default (recommended)  Opus 4.8 with 1M\n"
        "                              context\n"
        "    2. Opus                   Opus 4.8 with 1M\n"
        "                              context\n"
        "  ❯ 3. Fable ✔                Fable 5 · Most\n"
        "                              capable\n"
        "    4. Sonnet                 Sonnet 5\n"
        "                              Efficient\n"
        "    5. Haiku                  Haiku 4.5\n"
        "                              Fastest\n"
        "\n"
        "  Enter to set as default · s to use this\n"
        "  session only · Esc to cancel"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert verdict.input_mode == InputMode.NUMBERS
    assert verdict.options == ["1", "2", "3", "4", "5"]


def test_tail_hash_ignores_volatile_status_bar():
    """rate-limit の分カウントダウンや spinner 経過秒が動いても、 内容が同じなら
    hash は不変 (= 入力待ちの間に status bar の時計が進んでも idle 判定が壊れない)。"""
    body = "  ❯ 1. Yes\n    2. No\n"
    s1 = _snap(body + "  [Fable 5] 5h:60%(1h49m) 7d:23% ctx:42%")
    s2 = _snap(body + "  [Fable 5] 5h:59%(1h48m) 7d:23% ctx:42%")
    assert s1.tail_hash == s2.tail_hash


# ---------------------------------------------------------------------------
# Tier C: text prompts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tail, expected_category",
    [
        ("Do you want to remove file.txt? [Y/n] ", PromptCategory.CONFIRM_YN),
        ("This will remove 3 packages. Do you want to continue? [Y/n] ", PromptCategory.CONFIRM_YN),
        (
            "Are you sure you want to continue connecting (yes/no/[fingerprint])? ",
            PromptCategory.CONFIRM_YN,
        ),
        ("> Register MAAS as KVM host [default = no] : (y/N)", PromptCategory.CONFIRM_YN),
        ("[sudo] password for alice: ", PromptCategory.PASSWORD),
        ("Password:", PromptCategory.PASSWORD),
        ("Passphrase for key '/home/alice/.ssh/id_rsa': ", PromptCategory.PASSWORD),
        ("Enter OTP: ", PromptCategory.OTP),
        ("Please enter your one-time password: ", PromptCategory.OTP),
        ("  1) foo\n  2) bar\n#? ", PromptCategory.HASH_CHOICE),
    ],
)
def test_tier_c_categories(tail: str, expected_category: PromptCategory):
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    assert verdict.state == PromptState.TEXT_PROMPT, (
        f"expected TEXT_PROMPT for tail={tail!r}, got {verdict.state} ({verdict.reason})"
    )
    assert verdict.category == expected_category


def test_tier_c_pure_numbered_menu():
    tail = "Select an option:\n  1. foo\n  2. bar\n  3. baz"
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    assert verdict.state == PromptState.TEXT_PROMPT
    # `Select ... :` は generic_q_tail が先に、 それ以下は numbered_menu が hit。
    # 実装上 numbered_menu は先に評価されるので優先されるはず。
    assert verdict.category in (PromptCategory.NUMBERED_MENU, PromptCategory.GENERIC_QUESTION)


def test_tier_c_needs_idle():
    """idle threshold 未満なら「出力中」 として skip される。"""
    state = DetectorState()
    # 今初めて観測 → idle=0
    verdict = analyze(_snap("Password: ", now=100.0), state)
    assert verdict.state == PromptState.ACTIVE


def test_tier_c_needs_idle_after_input_grace():
    """input 送信直後は grace period で tier C を skip する。"""
    state = _prime_state("Password: ", idle_since=9.0)  # tier D 発火しないよう短めに
    state.record_input_sent(9.5)  # 0.5s 前に送信 → grace 内
    verdict = analyze(_snap("Password: ", now=10.0), state)
    # tier C は grace で skip、 idle も長期未満なので TEXT_PROMPT 以外に落ちる
    assert verdict.state != PromptState.TEXT_PROMPT


def test_tier_c_skipped_when_claude_tui_owns_screen():
    """実測 (= 2026-07-06): チャット本文の番号リストが pane に描画され、 numbered_menu
    regex に誤 hit した。 pane 末尾に Claude の status bar が見えている = Claude TUI が
    画面占有中 = subprocess の生 prompt は存在しえないので tier C は丸ごと skip。"""
    tail = (
        "修正案: 送信を 2 段に分ける:\n"
        "  1. text paste (Enter なし)\n"
        "  2. 短い delay を置いて Enter 単発送信\n"
        "──────────────────────────────\n"
        "❯ \n"
        "──────────────────────────────\n"
        "  [Fable 5] 5h:11%(4h49m) 7d:28% ctx:50%\n"
        "  ⏵⏵ bypass permissions on (shift+tab to"
    )
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    assert verdict.state != PromptState.TEXT_PROMPT


def test_tier_c_alive_without_claude_status_bar():
    """status bar が無い生 shell の prompt は従来どおり tier C が拾う。"""
    tail = "Do you want to remove file.txt? [Y/n] "
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    assert verdict.state == PromptState.TEXT_PROMPT


def test_tier_c_generic_fallback_only_at_tail():
    """会話 log 内で「[Y/n]」 が中間行に出るケース = 末尾でないので hit しない。"""
    tail = "The docs say [Y/n] is the confirm pattern.\nSee below.\n"
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    # 中間の [Y/n] は hit しない、 末尾は改行だけなので generic_q も miss。
    assert verdict.state != PromptState.TEXT_PROMPT


# ---------------------------------------------------------------------------
# Phase 4a: input_mode + options for quick-reply UI
# ---------------------------------------------------------------------------


def test_input_mode_numbers_for_claude_code_feedback_dialog():
    tail = (
        "● How is Claude doing this session?\n"
        "  1: Bad    2: Fine   3: Good   0: Dismiss\n"
        "──────────────────────────────────────\n"
        "❯ "
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert verdict.input_mode == InputMode.NUMBERS
    assert verdict.options == ["1", "2", "3", "0"]
    # Ink dialog は 1 打鍵で決定、 Enter 不要
    assert verdict.key_requires_enter is False


def test_input_mode_numbers_for_trust_folder_dialog():
    tail = (
        "──────────────────\n"
        " ❯ 1. Yes, I trust this folder\n"
        "   2. No, exit\n"
        "──────────────────"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert verdict.input_mode == InputMode.NUMBERS
    assert verdict.options == ["1", "2"]
    assert verdict.key_requires_enter is False


def test_input_mode_yn_for_confirm_prompt():
    tail = "Do you want to remove file.txt? [Y/n] "
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    assert verdict.state == PromptState.TEXT_PROMPT
    assert verdict.category == PromptCategory.CONFIRM_YN
    assert verdict.input_mode == InputMode.YN
    assert verdict.options == ["Y", "n"]
    # shell prompt は Enter 要
    assert verdict.key_requires_enter is True


def test_input_mode_numbers_for_bash_select():
    tail = "  1) foo\n  2) bar\n  3) baz\n#? "
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    assert verdict.state == PromptState.TEXT_PROMPT
    assert verdict.category == PromptCategory.HASH_CHOICE
    assert verdict.input_mode == InputMode.NUMBERS
    assert verdict.options == ["1", "2", "3"]
    assert verdict.key_requires_enter is True


def test_input_mode_none_for_password_prompt():
    tail = "[sudo] password for alice: "
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    assert verdict.state == PromptState.TEXT_PROMPT
    assert verdict.category == PromptCategory.PASSWORD
    # password は button 出さず手入力に任せる
    assert verdict.input_mode == InputMode.NONE
    assert verdict.options == []


# ---------------------------------------------------------------------------
# Tier D: long idle
# ---------------------------------------------------------------------------


def test_tier_d_long_idle():
    tail = "some quiet output\n"  # regex hit なし
    state = _prime_state(tail, idle_since=0.0)
    verdict = analyze(_snap(tail, now=10.0), state, DetectorConfig(long_idle_threshold_sec=5.0))
    assert verdict.state == PromptState.IDLE


def test_tier_d_short_idle_stays_active():
    tail = "some quiet output\n"
    state = _prime_state(tail, idle_since=8.0)  # 2s 前が起点
    verdict = analyze(_snap(tail, now=10.0), state, DetectorConfig(long_idle_threshold_sec=5.0))
    assert verdict.state == PromptState.ACTIVE


# ---------------------------------------------------------------------------
# bypass mode chip
# ---------------------------------------------------------------------------


def test_bypass_chip_extracted_regardless_of_tier():
    tail = "some output\n⏵⏵ bypass permissions on (shift+tab to cycle)"
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.bypass_mode_visible is True


def test_no_bypass_chip_when_absent():
    tail = "some output\n"
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.bypass_mode_visible is False


# ---------------------------------------------------------------------------
# Hash-based idle progression
# ---------------------------------------------------------------------------


def test_hash_unchanged_keeps_first_seen_at():
    state = DetectorState()
    s1 = _snap("waiting: [Y/n] ", now=10.0)
    analyze(s1, state)
    first_seen = state.hash_first_seen_at
    assert first_seen == 10.0
    # 同じ内容で 3 秒後 → hash 起点は動かない
    s2 = _snap("waiting: [Y/n] ", now=13.0)
    analyze(s2, state)
    assert state.hash_first_seen_at == first_seen


def test_hash_changed_resets_first_seen_at():
    state = DetectorState()
    analyze(_snap("first", now=10.0), state)
    analyze(_snap("second", now=13.0), state)
    assert state.hash_first_seen_at == 13.0


def test_tier_b_bare_arrow_ignores_dot_style_chat_list():
    """bare `❯` (= 入力欄) の直上にチャット本文の点区切り番号リストが描画された形は
    picker と判定しない (= 2026-07-06 会社 PC 実測の誤爆 class)。 bare arrow 救済は
    コロン区切りの横並び (= feedback dialog) に限定する。"""
    tail = "\n".join([
        "KID が実際にやってること (= 具体手順):",
        "  1. 正解 98 枚を Inception に通す → 98 個の数字リスト",
        "  2. 生成 98 枚を Inception に通す → 98 個の数字リスト",
        "  3. この 2 束の数字が平均的に似てるかを数式で測る",
        "  4. 小さい = 「生成 98 枚の読み取り結果が、 正解 98 枚と似てる」",
        "────────",
        "❯ ",
        "────────",
    ])
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state != PromptState.INLINE_TUI


def test_tier_b_bare_arrow_still_detects_colon_feedback_dialog():
    """コロン区切り横並び (= feedback dialog) は bare arrow でも従来通り検出する。"""
    tail = "How is Claude doing this session?\n1: Bad  2: Fine  3: Good  0: Dismiss\n❯ "
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI


# ---------------------------------------------------------------------------
# Tier B × ANSI (= 2026-07-07 転換: 装飾を構造情報として使う)
# ---------------------------------------------------------------------------

from backend.terminal.ansi_text import strip_ansi  # noqa: E402

_CYAN = "\x1b[36m"
_RESET = "\x1b[0m"


def _ansi_snap(ansi: str, *, alternate: bool = False, now: float = 100.0) -> TailSnapshot:
    """loop と同じ導出 (= tail_text は strip_ansi(ansi)) で snapshot を作る。"""
    return TailSnapshot(
        alternate_on=alternate, tail_text=strip_ansi(ansi), now_sec=now, ansi_tail=ansi
    )


def test_tier_b_glyphless_picker_via_unique_styled_option():
    """❯ glyph が無くても「唯一装飾された option 行」 を選択カーソルとみなす
    (= glyph が claude 更新で変わっても highlight 構造で拾う第 2 経路)。"""
    ansi = "\n".join([
        "Select a folder action:",
        f"{_CYAN}  1. Yes, I trust this folder{_RESET}",
        "  2. No, exit",
    ])
    verdict = analyze(_ansi_snap(ansi), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert "1" in verdict.options and "2" in verdict.options


def test_tier_b_glyphless_needs_unique_styled_line():
    """styled 行が 0 or 複数なら glyphless 経路は発動しない (= 判別不能は沈黙)。"""
    all_plain = "\n".join([
        "Select:",
        "  1. Yes",
        "  2. No",
    ])
    v = analyze(_snap(all_plain), _prime_state(all_plain))
    assert v.state != PromptState.INLINE_TUI

    both_styled = "\n".join([
        f"{_CYAN}  1. Yes{_RESET}",
        f"{_CYAN}  2. No{_RESET}",
    ])
    v2 = analyze(_ansi_snap(both_styled), _prime_state(strip_ansi(both_styled)))
    assert v2.state != PromptState.INLINE_TUI


def test_tier_b_ansi_veto_kills_unstyled_colon_cluster_near_bare_arrow():
    """bare arrow 救済経路の ANSI veto: tail に装飾があるのに候補 cluster が全行無装飾
    = チャット本文のコロン型例文 (= plain 描画) であって実 picker ではない → 却下。

    粒度の注意: signature は行単位。 チャット行がインラインコード等で部分装飾されて
    いると veto は届かない (= 既存のコロン限定 fence が第 1 防壁、 これは第 2 防壁)。"""
    ansi = "\n".join([
        "feedback dialog は 1: Bad  2: Fine  3: Good と出ます",  # チャット本文 (= 無装飾)
        "",
        "❯ ",
        f"{_CYAN}5h:60% | 7d:31%{_RESET}",  # status bar (= tail に装飾自体は存在する)
    ])
    verdict = analyze(_ansi_snap(ansi), _prime_state(strip_ansi(ansi)))
    assert verdict.state != PromptState.INLINE_TUI


def test_tier_b_bare_arrow_rescue_survives_when_cluster_is_styled():
    """実 feedback dialog (= コロン型 option が装飾付き) は veto されない。"""
    ansi = "\n".join([
        "How did Claude do?",
        f"{_CYAN}1: Bad  2: Fine  3: Good  0: Dismiss{_RESET}",
        "❯ ",
    ])
    verdict = analyze(_ansi_snap(ansi), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert verdict.options == ["1", "2", "3", "0"]


def test_tier_b_no_ansi_keeps_legacy_text_behaviour():
    """ansi_tail 無し (= 旧経路 / capture -e 失敗) は従来のテキストのみ判定に fallback。"""
    tail = "\n".join([
        "How did Claude do?",
        "1: Bad  2: Fine  3: Good  0: Dismiss",
        "❯ ",
    ])
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI


def test_tier_b_glyph_path_unchanged_with_ansi_present():
    """従来の「❯ が option 行に乗る」 主経路は ANSI があっても従来通り。"""
    ansi = "\n".join([
        f"{_CYAN}❯ 1. Yes, I trust this folder{_RESET}",
        "  2. No, exit",
    ])
    verdict = analyze(_ansi_snap(ansi), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert verdict.input_mode == InputMode.NUMBERS


# ---------------------------------------------------------------------------
# tier A 誤発火: alternate_on 立てっぱなし + status bar が末尾窓外 (= 2026-07-09)
# ---------------------------------------------------------------------------

def test_owns_screen_finds_status_bar_past_blank_lines_and_hints():
    """入力欄複数行 + status bar の下にヒント行/空行が挟まって status bar が末尾 4 行の外に
    出ても、 非空行末尾 8 行で拾って Claude TUI 占有と判定する (= banner 出っぱなし根治)。"""
    from backend.terminal.prompt_detector import _claude_tui_owns_screen
    tail = "\n".join([
        "9 tasks (8 done, 1 open)",
        "❯ ",
        "",
        "[Opus 4.8 (1M context)] 5h:10%(2h32m) 7d:44%",  # status bar
        "← for agents",                                   # ヒント行
        "",
        "",
    ])
    assert _claude_tui_owns_screen(tail) is True


def test_tier_a_suppressed_when_claude_tui_owns_screen_via_status_bar():
    """alternate_on=True でも、 末尾側に Claude TUI status bar が見える素の入力欄 pane は
    tier A の "TUI running" を出さない (= 画像の状況、 下位 tier に流れて ACTIVE)。"""
    tail = "\n".join([
        "Setup → Firmware Update → zip 選択 → 検証",
        "どう進めます?",
        "❯ ",
        "",
        "[Opus 4.8 (1M context)] 5h:10%(2h32m) 7d:44%",
        "← for agents",
    ])
    v = analyze(_snap(tail, alternate=True), _new_state())
    assert v.state != PromptState.TUI


def test_owns_screen_false_for_real_fullscreen_tui():
    """vim/less 等 status bar の無い本物の全画面 TUI は占有と誤判定しない (= tier A が生きる)。"""
    from backend.terminal.prompt_detector import _claude_tui_owns_screen
    tail = "\n".join([f"~ line {i}" for i in range(20)] + ["-- INSERT --"])
    assert _claude_tui_owns_screen(tail) is False
    v = analyze(_snap(tail, alternate=True), _new_state())
    assert v.state == PromptState.TUI
