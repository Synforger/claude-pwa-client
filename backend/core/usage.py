"""使用率系の状態 (= 5h/7d/ctx/model) を組み立てる層。

rate-limits.jsonl (= statusline 記録) の読み取りと、 usage からの context 使用率計算を
担当する。 state.py は純粋な state 定義・lifecycle に専念し、 「使用率の計算」 はここに
集約する (= 2026-05-17 責務分離)。

2026-06-21 (backend-F-11): tail 読み取りは `read_all_rate_limits_tail()` 一本に統合。
`read_latest_rate_limits` は in-memory filter ヘルパに整理した (= 旧版は file I/O を
2 関数で重複実装、 SSE で sid 数回叩く毎に同じ 32KB tail を再 parse していた)。
"""
import json
import logging
from pathlib import Path

import backend.config as _config
from backend.state import DEFAULT_CTX_WINDOW

logger = logging.getLogger(__name__)


def read_all_rate_limits_tail() -> list[dict]:
    """rate-limits.jsonl の末尾 32KB を 1 回読んで parse 済 list を返す (= 全 sid 共有用)。

    `_build_all_status` が複数 sid 分を 1 回の SSE で配るとき、 sid 毎に
    `read_latest_rate_limits` を呼ぶと同じ tail を sid 数回 read するので、 ここで 1 回
    にまとめて呼び出し側が in-memory filter する。 list は古→新の時系列順。"""
    path = _config.RATE_LIMITS_LOG_PATH
    if not path:
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 32768))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    parsed: list[dict] = []
    # 32KB 内で 200 行までは widen して見る (= 旧 read_latest 互換)、 末尾 100 行に
    # 絞らず広めに parse して、 latest_from_tail 側が account filter 後の末尾を選べる
    # ようにする。
    for ln in tail.splitlines()[-200:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            parsed.append(json.loads(ln))
        except (json.JSONDecodeError, ValueError):
            continue
    return parsed


def latest_from_tail(
    tail: list[dict],
    claude_sid: str | None = None,
    account_id: str | None = None,
) -> dict:
    """parse 済 tail (= `read_all_rate_limits_tail()` の戻り) から
    指定 sid / account の 5h/7d/ctx/model を組み立てる pure helper。

    file I/O 無し。 同じ tail を sid 数回 filter する SSE 経路で使う。"""
    if not tail:
        return {}
    if account_id:
        scoped = [p for p in tail if (p.get("account_id") or "personal") == account_id]
    else:
        scoped = tail
    if not scoped:
        return {}
    last = scoped[-1]
    if claude_sid:
        sess = next(
            (p for p in reversed(scoped) if p.get("session_id") == claude_sid), None
        )
    else:
        sess = last
    # 7d% flap 吸収: Anthropic 側集計が 85%↔1% で一時的に揺らぐ。 同じ
    # seven_day_resets_at を共有する直近行の中で max を採り単調側に寄せる。
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

    2026-06-21 (backend-F-11): 旧版は file I/O + filter を本関数 1 つで持っていた。
    `read_all_rate_limits_tail()` + `latest_from_tail()` の 2 段に分解し、 本関数は
    そのうち file I/O 経路だけを担う薄い wrapper に整理。 SSE 側は all_tail 1 回 +
    各 sid で latest_from_tail を呼べば I/O が 1 回で済む (= 旧来は sid 毎 1 I/O)。
    """
    return latest_from_tail(
        read_all_rate_limits_tail(),
        claude_sid=claude_sid,
        account_id=account_id,
    )


def rate_limits_log_health() -> tuple[bool, str]:
    """rate_limits_log path が「設定されてる + 親 dir が存在する + (任意で) file が
    読める」 を確認した 1 行サマリを返す (= backend-F-67 の sanity check 起動時用)。

    main.lifespan の validate_runtime_paths と組で呼ばれることを想定。 戻り値の
    bool は ok / not ok、 string は human readable な reason。
    """
    path = _config.RATE_LIMITS_LOG_PATH
    if not path:
        return False, "rate_limits_log not configured (= no statusline integration)"
    p = Path(path).expanduser()
    if not p.parent.is_dir():
        return False, f"parent dir missing: {p.parent}"
    if not p.exists():
        return True, f"path ok but file not yet created: {p}"
    return True, f"path ok: {p}"


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


