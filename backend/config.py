"""アプリ設定の読み込みと、複数モジュールから参照する定数。

config.json の I/O は **module import 時に走らせない** 設計に統一した
(2026-06-21、 finding backend-F-36)。 旧版は top-level で `open(CONFIG_PATH)`
を呼んでいたため、 pytest 経由で `backend.config` が import されるだけで
本物の `backend/config.json` が必要になり、 CI / 個人 worktree / sub-agent
環境では collection error で全 test が落ちていた。

- `get_config()` が唯一の読み手。 `@lru_cache` で 1 process 1 回だけ I/O。
- 旧来の module-level 定数 (`AGENTS` / `CORS_ALLOW_ORIGINS` / ...) は
  PEP 562 の `__getattr__` で **遅延で配信**する。 既存 consumer は
  `from backend.config import AGENTS` の書き方を変えなくて良い。
  test 側は `monkeypatch.setattr(backend.config, "CONFIG_PATH", ...)` +
  `get_config.cache_clear()` で挙動を差し替えられる (= 旧設計では import
  時点で値が固まっていて差し替え不能だった)。
- 起動時 sanity check は `validate_runtime_paths()` に集約し
  (backend-F-67)、 main.lifespan から 1 回だけ呼ぶ。
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.paths import CONFIG_PATH

logger = logging.getLogger(__name__)

HOME = Path.home()
FILE_SIZE_LIMIT = 1 * 1024 * 1024  # 1MB
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """config.json を 1 度だけ読んで dict を返す。

    file が無い場合は空 dict にフォールバックする (= test 環境で minimum
    fixture を流し込めるよう、 import 時には絶対に I/O 失敗で落ちない)。
    実機運用では main.lifespan で `validate_runtime_paths()` を呼んで
    重要キーの欠落を warn ログに出す。
    """
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(
            "config.json not found at %s; running with empty config "
            "(suitable for tests only).",
            CONFIG_PATH,
        )
        return {}
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load config.json at %s", CONFIG_PATH)
        return {}


def _projects_dirs_from_accounts(accounts: dict[str, Any]) -> list[Path]:
    """ACCOUNTS の env.CLAUDE_CONFIG_DIR から projects ディレクトリ候補を集める。
    デフォルト `~/.claude/projects` は常に含める (= account_id=None 互換)。
    """
    dirs: list[Path] = [Path.home() / ".claude" / "projects"]
    for cfg in accounts.values():
        env = (cfg or {}).get("env") or {}
        d = env.get("CLAUDE_CONFIG_DIR")
        if d:
            p = Path(d).expanduser() / "projects"
            if p not in dirs:
                dirs.append(p)
    return dirs


def projects_dir_for_account(account_id: str | None) -> Path:
    """session の account_id から projects ディレクトリを返す。 該当が無ければ personal
    (= ~/.claude/projects) にフォールバック。
    """
    if account_id:
        env = (get_config().get("accounts", {}).get(account_id) or {}).get("env") or {}
        d = env.get("CLAUDE_CONFIG_DIR")
        if d:
            return Path(d).expanduser() / "projects"
    return Path.home() / ".claude" / "projects"


def default_account_id() -> str | None:
    """account_id 未設定の session が実際に使っている account の id を返す。

    account_id が無い session は projects_dir_for_account(None) 経由で既定の
    `~/.claude/projects` を読む。 それと同じ場所を指す account (= env に CLAUDE_CONFIG_DIR を
    持たない最初のもの) が「未設定と等価な account」。 これを解決しないと、 古い session
    (= account_id が None のまま作られたタブ) が「どのアカウントにも属さない」 扱いになり、
    自分自身が移行先候補に出てしまう。

    account の一覧は `_accounts()` から取る (= `accounts` を書いていない設定では既定の 1 つ)。
    生の設定を読むと、 その構成でだけ一覧と既定が食い違う。
    """
    for name, cfg in _accounts().items():
        env = (cfg or {}).get("env") or {}
        if not env.get("CLAUDE_CONFIG_DIR"):
            return name
    return None


def cwd_to_project_dirname(cwd: str) -> str:
    """claude Code の規約: パス中の `/` と `.` を `-` に置換 (先頭 `/` も `-`)。"""
    return cwd.replace("/", "-").replace(".", "-")


def cwd_to_project_dir(cwd: str, account_id: str | None = None) -> Path:
    """cwd → projects ディレクトリ。 account_id が指定されてれば該当アカウントの
    projects dir、 指定なしなら personal (= ~/.claude/projects)。

    純粋な path 計算 (= config の accounts 情報にのみ依存) なのでここが真値。
    core.jsonl_watcher は互換 alias (`_cwd_to_project_dir`) で再公開する (= state 等の
    下位層が jsonl を import しなくて済む)。
    """
    return projects_dir_for_account(account_id) / cwd_to_project_dirname(cwd)


# 連絡を運び合う別の機械の backend (= agent_message_peers)。 名前は宛先の `<名前>:<タブ>` の左側に
# そのまま使うので、 `:` を含まない英数字・ハイフン・下線の 32 文字までに絞る。
PEER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def _agent_message_peers(raw: Any) -> dict[str, dict[str, Any]]:
    """config の `agent_message_peers` のうち、 形の正しい相手だけを返す (= 1 件の書き損じで全部は消えない)。

        {"<名前>": {"url": "https://...", "address": "<その相手からの呼び出しが届く時の接続元>",
                    "accounts": ["<この相手と連絡してよいタブの account>", ...]}}

    accounts は省ける (= 省けば全部のタブ)。 url はこちらから送る先、 address は向こうから届いた呼び出しを
    その相手の物と認める接続元 (= 両方が揃って 1 つの相手)。
    """
    peers: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return peers
    for name, entry in raw.items():
        if not (isinstance(name, str) and PEER_NAME_RE.match(name) and isinstance(entry, dict)):
            continue
        url, address, accounts = entry.get("url"), entry.get("address"), entry.get("accounts")
        if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
            continue
        if not (isinstance(address, str) and address.strip()):
            continue
        if accounts is not None and not (isinstance(accounts, list) and all(isinstance(a, str) for a in accounts)):
            continue
        peers[name] = {"url": url.rstrip("/"), "address": address.strip(), "accounts": accounts}
    return peers


def _accounts() -> dict[str, Any]:
    return get_config().get("accounts") or {
        "personal": {"display_name": "Personal", "env": {}}
    }


# --- 拡張 (= 別 repo のアプリを iframe で嵌める口) ---
# 拡張の置き場は `/ext/<id>/` に固定する (= config に path を書かせない)。 id は URL の 1 段と
# DOM の識別子にそのまま使うので、 英小文字・数字・ハイフンの 32 文字までに絞る。
EXTENSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
EXTENSION_DEFAULT_ICON = "🧩"
# 拡張の開き方。 band = チャットの上の帯 (= 高さを変えられ、 チャットと並べて使う)、 page = 入力欄の上を
# 全部使う頁 (= 読み物。 開いている間はメッセージの一覧の場所に出る)。 書かなければ band。
EXTENSION_VIEWS = ("band", "page")
EXTENSION_DEFAULT_VIEW = "band"


def _scan_extensions() -> tuple[list[dict[str, str]], list[str]]:
    """config.json の `extensions` を (= 採用した拡張, 書き損じの指摘) に分ける。

    捨てるのは id が不正な 1 件だけで、 残りは生かす (= 1 件の書き損じで全拡張が消えない)。
    `view` の書き損じは捨てずに既定の開き方で採用する (= 拡張は使えるまま、 指摘だけ残す)。
    指摘の文面は起動時の warn にそのまま使う。
    """
    raw = get_config().get("extensions")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"config.extensions must be a list, got {type(raw).__name__}"]
    accepted: list[dict[str, str]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        ext_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(ext_id, str) or not EXTENSION_ID_RE.match(ext_id):
            problems.append(
                f"config.extensions[{i}] dropped: id must match {EXTENSION_ID_RE.pattern}"
            )
            continue
        if ext_id in seen:
            problems.append(f"config.extensions[{i}] dropped: duplicate id {ext_id!r}")
            continue
        seen.add(ext_id)
        title = entry.get("title")
        icon = entry.get("icon")
        view = entry.get("view", EXTENSION_DEFAULT_VIEW)
        if view not in EXTENSION_VIEWS:
            problems.append(
                f"config.extensions[{i}]: view must be one of {', '.join(EXTENSION_VIEWS)}, "
                f"got {view!r}; using {EXTENSION_DEFAULT_VIEW!r}"
            )
            view = EXTENSION_DEFAULT_VIEW
        accepted.append({
            "id": ext_id,
            "title": title if isinstance(title, str) and title else ext_id,
            "icon": icon if isinstance(icon, str) and icon else EXTENSION_DEFAULT_ICON,
            "path": f"/ext/{ext_id}/",
            "view": view,
        })
    return accepted, problems


def extensions() -> list[dict[str, str]]:
    """採用した拡張を config の順で返す (= path は id から導出済み)。"""
    return _scan_extensions()[0]


def validate_runtime_paths() -> None:
    """起動時 sanity check (= backend-F-67)。 主要 path / 設定の欠落を warn する。

    値が落ちていても落ちないが、 観測点を残して「何でうまく動かないか」 を
    log に固定する。 main.lifespan からのみ呼ぶ。
    """
    cfg = get_config()
    if not cfg:
        logger.warning(
            "runtime check: config.json is empty; agents / accounts / "
            "webpush startup paths will be no-ops."
        )
        return
    if "agents" not in cfg or not cfg.get("agents"):
        logger.warning("runtime check: config.agents is missing/empty.")
    rate_path = cfg.get("rate_limits_log") or ""
    if rate_path:
        if not Path(rate_path).expanduser().parent.is_dir():
            logger.warning(
                "runtime check: rate_limits_log parent dir does not exist: %s",
                rate_path,
            )
    map_dir = cfg.get("tmux_session_map_dir") or ""
    if map_dir and not Path(map_dir).expanduser().is_dir():
        logger.warning(
            "runtime check: tmux_session_map_dir does not exist: %s", map_dir
        )
    for problem in _scan_extensions()[1]:
        logger.warning("runtime check: %s", problem)


# --- 旧 module-level 定数の遅延配信 (PEP 562) ---
# 既存 consumer (= `from backend.config import AGENTS` 等) を変えないために
# `__getattr__` で必要時に config を引いて返す。 lookup ごとに get_config() を
# 呼ぶが、 内側で lru_cache されているので I/O は 1 回。
def __getattr__(name: str) -> Any:  # noqa: PLR0911
    cfg = get_config()
    if name == "AGENTS":
        return cfg.get("agents") or {}
    if name == "ACCOUNTS":
        return _accounts()
    if name == "CLAUDE_PROJECTS_DIRS":
        return _projects_dirs_from_accounts(_accounts())
    if name == "UPLOADS_TMP":
        return Path(
            cfg.get("uploads_tmp", str(HOME / ".claude-pwa-client" / "uploads" / "tmp"))
        ).expanduser()
    if name == "CLAUDE_PATH":
        return cfg.get("claude_path")
    if name in ("AGENT_MESSAGE_CHECK", "AGENT_MESSAGE_OPERATOR_CHECK"):
        check = cfg.get(name.lower())
        return check if isinstance(check, list) and all(isinstance(w, str) for w in check) else []
    if name == "AGENT_MESSAGE_PEERS":
        return _agent_message_peers(cfg.get("agent_message_peers"))
    if name == "CORS_ALLOW_ORIGINS":
        return cfg.get("cors_allow_origins", [])
    if name == "RATE_LIMITS_LOG_PATH":
        return cfg.get("rate_limits_log", "")
    if name == "TMUX_SESSION_MAP_DIR":
        return cfg.get("tmux_session_map_dir", "")
    if name == "VAPID_SUB":
        return cfg.get("vapid_sub", "mailto:admin@example.com")
    if name == "NOTIFICATION_TITLE_DEFAULT":
        return cfg.get("notification_title", "Notification")
    raise AttributeError(f"module 'backend.config' has no attribute {name!r}")
