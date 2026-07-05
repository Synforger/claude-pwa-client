"""prompt_detector の pure 判定を実測パターンで verify する。

verify script (= 実 tmux / 実 CLI) で観測した 12+ の prompt tail を fixture 化し、
tier A / B / C / D が期待通りに hit するかを確認する。
"""
from __future__ import annotations

import pytest

from backend.terminal.prompt_detector import (
    DetectorConfig,
    DetectorState,
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


# ---------------------------------------------------------------------------
# Tier B: inline TUI (❯ + 罫線 / ❯ 単独)
# ---------------------------------------------------------------------------


def test_tier_b_claude_code_trust_folder():
    """実測: Claude Code の trust folder prompt (= ❯ + ─ 罫線)。"""
    tail = (
        "────────────────────────────────────────────────\n"
        " ❯ 1. Yes, I trust this folder\n"
        "   2. No, exit\n"
        "────────────────────────────────────────────────"
    )
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert "1. Yes, I trust this folder" in verdict.excerpt


def test_tier_b_inquirer_bare_arrow():
    tail = "? Which environment:\n❯ development\n  staging\n  production"
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.INLINE_TUI
    assert "❯ development" in verdict.excerpt


def test_tier_b_no_arrow_no_hit():
    """罫線 (= ─) だけの chat 出力 (= region separator) を inline TUI にしない。"""
    tail = "some output\n────────\nmore output"
    verdict = analyze(_snap(tail), _new_state())
    assert verdict.state == PromptState.ACTIVE


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


def test_tier_c_generic_fallback_only_at_tail():
    """会話 log 内で「[Y/n]」 が中間行に出るケース = 末尾でないので hit しない。"""
    tail = "The docs say [Y/n] is the confirm pattern.\nSee below.\n"
    verdict = analyze(_snap(tail, now=10.0), _prime_state(tail, idle_since=0.0))
    # 中間の [Y/n] は hit しない、 末尾は改行だけなので generic_q も miss。
    assert verdict.state != PromptState.TEXT_PROMPT


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
