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
import os
import re
from pathlib import Path

import backend.config as _config
from backend.state import DEFAULT_CTX_WINDOW

logger = logging.getLogger(__name__)


# 起動直後に file を後ろから遡る時の 1 回の読み幅。
_BACKWARD_CHUNK_BYTES = 1 << 20
_ACCOUNT_RE = re.compile(rb'"account_id":\s*"([^"]*)"')


class _LatestRows:
    """rate-limits.jsonl の「アカウントごと・session ごとの最新行」 を持ち続ける。

    rate-limits.jsonl は全アカウント・全 session が statusline の更新ごとに 1 行ずつ
    追記する共有 file。 旧実装は末尾 200 行だけを見ていたため、 片方のアカウントが
    休んでいる間にもう片方が 200 回更新すると、 休んでいる側の行が窓から押し出されて
    5h / 7d が空 (= 画面では 0) になった。 ここでは前回読んだ位置を覚えて追記分だけを
    読み、 各キーの最新行を上書きで持つので、 どれだけ前の行でも失われない。

    起動直後 (= 位置が無い) だけは file を後ろから遡り、 設定にある全アカウントの
    最新行が見つかった所で止める。 file の差し替え / 切り詰めを見たら最初から持ち直す。"""

    def __init__(self) -> None:
        self._reset(None)

    def _reset(self, ident: tuple | None) -> None:
        self._ident = ident
        self._offset = 0
        self._partial = b""
        self._seq = 0
        self._rows: dict[tuple[str, str], tuple[int, dict]] = {}

    def _add(self, row: dict) -> None:
        self._seq += 1
        self._rows[("account", row.get("account_id") or "personal")] = (self._seq, row)
        sid = row.get("session_id")
        if sid:
            self._rows[("session", sid)] = (self._seq, row)

    def _feed(self, data: bytes) -> None:
        buf = self._partial + data
        lines = buf.split(b"\n")
        self._partial = lines.pop()  # 改行で終わっていない最後の行は書き込み途中
        for ln in lines:
            row = _parse_line(ln)
            if row is not None:
                self._add(row)

    def _load_backward(self, f, size: int) -> None:
        wanted = set(_configured_accounts())
        found: set[str] = set()
        newest_first: list[dict] = []
        # 改行で終わっていない最後の行は書き込み途中なので、 次の追記と繋いで読む。
        f.seek(max(0, size - _BACKWARD_CHUNK_BYTES))
        last = f.read()
        cut = last.rfind(b"\n")
        end = size - (len(last) - cut - 1) if cut >= 0 else size - len(last)
        self._partial = last[cut + 1:] if cut >= 0 else last
        pos, carry, first = end, b"", True
        while pos > 0:
            start = max(0, pos - _BACKWARD_CHUNK_BYTES)
            f.seek(start)
            lines = (f.read(pos - start) + carry).split(b"\n")
            carry = lines.pop(0) if start > 0 else b""
            pos = start
            for ln in reversed(lines):
                m = _ACCOUNT_RE.search(ln)
                acct = m.group(1).decode("utf-8", "replace") if m else "personal"
                # 最新の読み幅は session ごとの最新行のために全部読む。 それより前は
                # まだ見つかっていないアカウントの行だけを parse する。
                if not first and acct in found:
                    continue
                row = _parse_line(ln)
                if row is not None:
                    newest_first.append(row)
                    found.add(acct)
            first = False
            # 設定にアカウントが無ければ、 最新の読み幅だけで止める。
            if not wanted or wanted <= found:
                break
        for row in reversed(newest_first):
            self._add(row)
        self._offset = size

    def rows(self, path: str) -> list[dict]:
        try:
            with open(path, "rb") as f:
                st = os.fstat(f.fileno())
                ident = (path, st.st_dev, st.st_ino)
                if ident != self._ident or st.st_size < self._offset:
                    self._reset(ident)
                    self._load_backward(f, st.st_size)
                elif st.st_size > self._offset:
                    f.seek(self._offset)
                    data = f.read(st.st_size - self._offset)
                    self._offset += len(data)
                    self._feed(data)
        except OSError:
            return []
        seen: set[int] = set()
        out: list[dict] = []
        for _, row in sorted(self._rows.values(), key=lambda v: v[0]):
            if id(row) not in seen:
                seen.add(id(row))
                out.append(row)
        return out


def _parse_line(ln: bytes) -> dict | None:
    ln = ln.strip()
    if not ln:
        return None
    try:
        row = json.loads(ln)
    except (json.JSONDecodeError, ValueError):
        return None
    return row if isinstance(row, dict) else None


def _configured_accounts() -> list[str]:
    try:
        return list((_config.get_config().get("accounts") or {}).keys())
    except Exception:
        return []


_LATEST = _LatestRows()


def read_all_rate_limits_tail() -> list[dict]:
    """rate-limits.jsonl から「アカウントごと・session ごとの最新行」 を古→新の順で返す
    (= 全 sid 共有用)。

    `_build_all_status` が複数 sid 分を 1 回の SSE で配るとき、 sid 毎に
    `read_latest_rate_limits` を呼ぶと同じ file を sid 数回 read するので、 ここで 1 回
    にまとめて呼び出し側が in-memory filter する。 各アカウントの最新行が必ず含まれる
    ので、 呼び出し側は account で絞った末尾をそのまま最新値として使える。"""
    path = _config.RATE_LIMITS_LOG_PATH
    if not path:
        return []
    return _LATEST.rows(path)


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
    # 5h / 7d は Anthropic の最新値 (= last 行の値) をそのまま採る。 旧実装は 7d 側で
    # 「同 seven_day_resets_at を共有する行の max」 を採る flap 吸収を持っていたが、 これは
    # Anthropic 側の恒久減少 (= 集計訂正 / モデル追加時の特例リセット等) を「flap」 として
    # 塗り潰し、 実 report が下がっても window 終わりまで高い値に pin される事故を招いた
    # (= 2026-07-02 personal account 74% pin、 実値 12% 観測)。 source-of-truth を素直に
    # 追い、 短時間 flap が実際に問題化した時にはその時点で個別に扱う。
    return {
        "five_hour_pct": last.get("five_hour_pct"),
        "seven_day_pct": last.get("seven_day_pct"),
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


