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


def _accounts() -> dict[str, Any]:
    return get_config().get("accounts") or {
        "personal": {"display_name": "個人", "env": {}}
    }


def validate_runtime_paths() -> None:
    """起動時 sanity check (= backend-F-67)。 主要 path / 設定の欠落を warn する。

    値が落ちていても落ちないが、 観測点を残して「何でうまく動かないか」 を
    log に固定する。 main.lifespan からのみ呼ぶ。
    """
    cfg = get_config()
    if not cfg:
        logger.warning(
            "runtime check: config.json is empty; agents / accounts / "
            "webpush 等の起動経路は no-op になります。"
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
