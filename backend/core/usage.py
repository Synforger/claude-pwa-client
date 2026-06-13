"""使用率系の状態 (= 5h/7d/ctx/model) を組み立てる層。

rate-limits.jsonl (= statusline 記録) の読み取りと、 usage からの context 使用率計算を
担当する。 state.py は純粋な state 定義・lifecycle に専念し、 「使用率の計算」 はここに
集約する (= 2026-05-17 責務分離)。
"""
import json

from config import RATE_LIMITS_LOG_PATH
from state import DEFAULT_CTX_WINDOW


def read_all_rate_limits_tail() -> list[dict]:
    """rate-limits.jsonl の末尾 32KB を 1 回読んで parse 済 list を返す (= 全 sid 共有用)。

    `_build_all_status` が複数 sid 分を 1 回の SSE で配るとき、 sid 毎に
    `read_latest_rate_limits` を呼ぶと同じ tail を sid 数回 read するので、 ここで 1 回
    にまとめて呼び出し側が in-memory filter する。 list は古→新の時系列順。"""
    if not RATE_LIMITS_LOG_PATH:
        return []
    try:
        with open(RATE_LIMITS_LOG_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 32768))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    parsed: list[dict] = []
    for ln in tail.splitlines()[-100:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            parsed.append(json.loads(ln))
        except (json.JSONDecodeError, ValueError):
            continue
    return parsed


def read_latest_rate_limits(
    claude_sid: str | None = None,
    account_id: str | None = None,
) -> dict:
    """rate-limits.jsonl (= statusline が記録) から 5h/7d/ctx/model を読む。

    proxy を一切使わず、 claude CLI 自身が statusline subprocess に渡す使用率を
    ファイル経由で拾う。 ファイル末尾だけ読んで軽く済ませる。 値が取れなければ空 dict
    (= 呼び出し側は既存 shared_status / agent_status を維持)。

    rate-limits.jsonl は全 claude セッション共有の 1 ファイルだが、 各行は
    `session_id` (= claude_sid) と `account_id` (= personal / work / ...) を持つ。
    **5h/7d はアカウント別に Anthropic 側で計測される**ので、 必ず account_id でフィルタ
    した最新行を使う (= 個人タブで会社の使用率が混ざるのを防ぐ)。 model / ctx は
    session ごとなので claude_sid 一致の最新行を採る。 該当無しなら None を返して
    呼び出し側 (= per-session agent_status) に fallback させる。
    """
    if not RATE_LIMITS_LOG_PATH:
        return {}
    try:
        with open(RATE_LIMITS_LOG_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # 複数 session が交互に書くので、 目的 session の直近行を拾えるよう広めに読む。
            f.seek(max(0, size - 32768))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return {}
    parsed: list[dict] = []
    for ln in lines[-200:]:
        try:
            parsed.append(json.loads(ln))
        except (json.JSONDecodeError, ValueError):
            continue
    if not parsed:
        return {}
    # account_id 指定時はその account の record だけ使う。 record に account_id 欄が
    # 無い旧版は "personal" 扱い (= 単一 OAuth 運用との後方互換)。
    if account_id:
        scoped = [p for p in parsed if (p.get("account_id") or "personal") == account_id]
    else:
        scoped = parsed
    if not scoped:
        return {}
    last = scoped[-1]  # アカウント別の集計 (= 5h/7d) は同 account 内最新行
    # model / ctx は session ごと。 claude_sid 指定時はその session の最新行から取る。
    if claude_sid:
        sess = next(
            (p for p in reversed(scoped) if p.get("session_id") == claude_sid), None
        )
    else:
        sess = last
    # 7d% flap 吸収: Anthropic 側集計が 85%↔1% で一時的に揺らぐ。 同じ
    # seven_day_resets_at を共有する直近行の中で max を採り単調側に寄せる。 account
    # filter 済の scoped 内だけで計算 = 他 account の値は混ざらない。
    cur_reset = last.get("seven_day_resets_at")
    seven_day_pct = last.get("seven_day_pct")
    same_window = [
        p.get("seven_day_pct") for p in scoped
        if p.get("seven_day_resets_at") == cur_reset
        and isinstance(p.get("seven_day_pct"), (int, float))
    ]
    if same_window:
        seven_day_pct = max(same_window)
    return {
        "five_hour_pct": last.get("five_hour_pct"),
        "seven_day_pct": seven_day_pct,
        "five_hour_resets_at": last.get("five_hour_resets_at"),
        "seven_day_resets_at": last.get("seven_day_resets_at"),
        "context_pct": sess.get("context_pct") if sess else None,
        "model": sess.get("model") if sess else None,
    }


def compute_ctx_pct(usage: dict, ctx_window: int = DEFAULT_CTX_WINDOW) -> int:
    """AssistantMessage.usage 辞書から context 使用率 % を計算。"""
    if not usage or ctx_window <= 0:
        return 0
    total = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )
    return min(round(total / ctx_window * 100), 100)


def format_model_name(key: str) -> str:
    """ResultMessage.model_usage キー (= "claude-opus-4-1-..." / "claude-fable-5") を
    「Opus 4.1」 / 「Fable 5」 形式に統一する (= 系列名 + 半角スペース + version)。"""
    key = key.replace("claude-", "")
    parts = key.split("-")
    if len(parts) >= 2:
        name = parts[0].capitalize()
        version = ".".join(parts[1:])
        return f"{name} {version}"
    return key.capitalize()


