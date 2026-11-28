"""アプリ設定の読み込みと、複数モジュールから参照する定数。

config.json の I/O は **module import 時に走らせない** 設計に統一した
(2026-06-21、 finding backend-F-36)。 旧版は top-level で `open(CONFIG_PATH)`
を呼んでいたため、 pytest 経由で `backend._common.config` が import されるだけで
本物の `backend/config.json` が必要になり、 CI / 個人 worktree / sub-agent
環境では collection error で全 test が落ちていた。

- `get_config()` が唯一の読み手。 `@lru_cache` で 1 process 1 回だけ I/O。
- 旧来の module-level 定数 (`AGENTS` / `CORS_ALLOW_ORIGINS` / ...) は
  PEP 562 の `__getattr__` で **読むたびに作って配信**する。 使う側は
  `from backend._common import config as _config` を頭に置き、 使う所で `_config.AGENTS` と読む。
  `from backend._common.config import AGENTS` と頭で書くと、 import の時に 1 回だけ値を束ねた写しになり、
  設定を読み直しても (test が設定を差し替えても) その module だけ古い値を見続ける
  (= `tests/architecture/test_config_read_at_use.py` が赤にする)。
  test 側は `monkeypatch.setattr(backend._common.config, "CONFIG_PATH", ...)` +
  `get_config.cache_clear()` で挙動を差し替えられる (= 旧設計では import
  時点で値が固まっていて差し替え不能だった)。
- 起動時 sanity check は `validate_runtime_paths()` に集約し
  (backend-F-67)、 main.lifespan から 1 回だけ呼ぶ。
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend._common.page_folders import folder_list_problem
from backend._common.paths import CONFIG_PATH, DOCUMENT_CACHE_DIR, RATE_LIMITS_LOG_DEFAULT, UPLOADS_TMP_DIR

logger = logging.getLogger(__name__)

HOME = Path.home()
FILE_SIZE_LIMIT = 1 * 1024 * 1024  # 1MB
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _read_config_file() -> dict[str, Any]:
    """config.json を読んで返す。 読めない時は例外 (= file が無い・読めない・JSON として壊れている)。"""
    with open(CONFIG_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """config.json を 1 度だけ読んで dict を返す (= 読み直すのは `reload_config()` だけ)。

    file が無い場合は空 dict にフォールバックする (= test 環境で minimum
    fixture を流し込めるよう、 import 時には絶対に I/O 失敗で落ちない)。
    実機運用では main.lifespan で `validate_runtime_paths()` を呼んで
    重要キーの欠落を warn ログに出す。
    """
    try:
        return _read_config_file()
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


# 読み直しの時に、 古い dict の中身を入れ替えて同じ物を使い続ける節。 `from backend._common.config import AGENTS`
# は import 時の dict をそのまま持ち続けるので、 別の dict に差し替えると、 そう書いた側だけ古い値を読み続ける。
_SHARED_SECTIONS = ("agents", "accounts")


def reload_config() -> dict[str, Any]:
    """config.json を読み直し、 次の `get_config()` から新しい値を返させる。 読めない時は例外を投げて今の値を残す。

    `agents` と `accounts` は同じ dict の中身を入れ替える (= `_SHARED_SECTIONS`)。 設定の書き換えで効く欄
    (逃げ先・止める線・眠り・入れ替え・通知の題・子の上限) は、 起動時に 1 度しか読まない所が無いので、
    次の見回りからこの値で動く。
    """
    _read_config_file()
    previous = get_config()
    get_config.cache_clear()
    fresh = get_config()
    for name in _SHARED_SECTIONS:
        old, new = previous.get(name), fresh.get(name)
        if isinstance(old, dict) and isinstance(new, dict):
            for key in [key for key in old if key not in new]:
                del old[key]
            old.update(new)
            fresh[name] = old
    return fresh


def entity_key(path: Path) -> tuple[int, int] | None:
    """What names the file or folder `path` is, whichever way it is spelled (a link and its target give the same key):
    its device and inode. None when it does not exist."""
    try:
        status = os.stat(path)
    except OSError:
        return None
    return status.st_dev, status.st_ino


def _projects_dirs_from_accounts(accounts: dict[str, Any]) -> list[Path]:
    """ACCOUNTS の env.CLAUDE_CONFIG_DIR から projects ディレクトリ候補を集める。
    デフォルト `~/.claude/projects` は常に含める (= account_id=None 互換)。
    A folder that is the same folder as one already listed (= the accounts share their records through a link) is
    listed once, so that no record is counted twice.
    """
    dirs: list[Path] = [Path.home() / ".claude" / "projects"]
    seen = {entity_key(dirs[0])} - {None}
    for cfg in accounts.values():
        env = (cfg or {}).get("env") or {}
        d = env.get("CLAUDE_CONFIG_DIR")
        if d:
            p = Path(d).expanduser() / "projects"
            key = entity_key(p)
            if p not in dirs and key not in seen:
                dirs.append(p)
                seen.add(key)
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


def projects_shared(account_a: str | None, account_b: str | None) -> bool:
    """Whether the conversation records of the two accounts are one folder: their `projects` folders are the same
    folder (one is a link to the other). False when either does not exist or is not an account of the configuration,
    so a machine whose accounts keep separate folders is judged as it always was."""
    if any(account is not None and account not in _accounts() for account in (account_a, account_b)):
        return False
    key = entity_key(projects_dir_for_account(account_a))
    return key is not None and key == entity_key(projects_dir_for_account(account_b))


def accounts_sharing(folder: Path) -> list[str]:
    """The accounts of the configuration whose `projects` folder is `folder` (the same folder, however spelled)."""
    key = entity_key(folder)
    if key is None:
        return []
    return [name for name in _accounts() if entity_key(projects_dir_for_account(name)) == key]


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


# --- ページの origin (= 指定の folder の HTML を、 sandbox を外して別の port から配る) ---

def _scan_page_origin() -> tuple[tuple[Path, int] | None, list[str]]:
    """config.json の `page_origin` を (= (folder, port) か None, 書き損じの指摘) に分ける。

    書いていない時と、 書き損じた時は None (= 別の port を立てず、 その folder の HTML も今どおり /file/view で開く)。
    folder は `~` を展開し、 symlink を辿った実体にする (= /file/open が resolve() した path と比べるため)。
    """
    raw = get_config().get("page_origin")
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, [f"config.page_origin must be an object, got {type(raw).__name__}"]
    folder, port = raw.get("folder"), raw.get("port")
    problems = []
    if not isinstance(folder, str) or not folder:
        problems.append("config.page_origin.folder must be a path")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        problems.append(f"config.page_origin.port must be a port number, got {port!r}")
    listed_problem = folder_list_problem(raw.get("folders"))
    if listed_problem:
        problems.append(listed_problem)
    if problems:
        return None, problems
    path = Path(folder).expanduser().resolve()
    if not path.is_dir():
        return None, [f"config.page_origin.folder is not a directory: {path}"]
    return (path, port), []


def page_origin() -> tuple[Path, int] | None:
    """sandbox を外して配る folder と、 それを配る port (= 書いていなければ None)。"""
    return _scan_page_origin()[0]


def page_folders() -> tuple[str, ...] | None:
    """page_origin の folder の中で配る folder の一覧 (= None は folder の全部)。 一覧の書き損じは page_origin ごと
    None になり、 何も配らない。"""
    if page_origin() is None:
        return None
    listed = get_config()["page_origin"].get("folders")
    return None if listed is None else tuple(listed)


# --- 資料 (= pdf・Office・tif を頁の画像に変えた物の控え) ---

DOCUMENTS_CACHE_MAX_MB_DEFAULT = 1024


def _scan_documents() -> tuple[tuple[Path, int], list[str]]:
    """config.json の `documents` を ((控えの置き場, 控えの上限の byte), 書き損じの指摘) に分ける。

    書き損じた欄は既定に戻す (= 資料は開けなくならない)。 置き場の既定は `paths.DOCUMENT_CACHE_DIR` (= repo の外)。
    """
    cache_dir, max_mb = DOCUMENT_CACHE_DIR, DOCUMENTS_CACHE_MAX_MB_DEFAULT
    raw = get_config().get("documents")
    problems: list[str] = []
    if raw is not None and not isinstance(raw, dict):
        problems.append(f"config.documents must be an object, got {type(raw).__name__}")
    elif raw:
        folder, limit = raw.get("cache_dir"), raw.get("cache_max_mb")
        if folder is not None:
            if isinstance(folder, str) and folder:
                cache_dir = Path(folder).expanduser().resolve()
            else:
                problems.append("config.documents.cache_dir must be a path")
        if limit is not None:
            if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit > 0:
                max_mb = limit
            else:
                problems.append(f"config.documents.cache_max_mb must be a positive number, got {limit!r}")
    return (cache_dir, int(max_mb * 1024 * 1024)), problems


def documents_settings() -> tuple[Path, int]:
    """資料の変換結果の控えの置き場と、 その大きさの上限 (byte)。"""
    return _scan_documents()[0]


# The sections of an agent a tier may replace (`agents.<agent>.tiers.<tier>`); every other key is the agent's.
TIER_SETTING_KEYS = ("rollover", "sleep")


def tier_setting_problems(agents: object) -> list[str]:
    """What is miswritten in the agents' `tiers`: a tier the agent's folder does not have, a key no tier replaces, or a
    value that is not an object. The readers then take the agent's own sections, so each would go unnoticed."""
    problems: list[str] = []
    for agent_id, agent in (agents.items() if isinstance(agents, dict) else ()):
        tiers = agent.get("tiers") if isinstance(agent, dict) else None
        if tiers is None:
            continue
        if not isinstance(tiers, dict):
            problems.append(f"config.agents.{agent_id}.tiers must be an object of tiers")
            continue
        folder = Path(str(agent.get("cwd") or "")).expanduser()
        for tier, section in tiers.items():
            where = f"config.agents.{agent_id}.tiers.{tier}"
            if not isinstance(section, dict):
                problems.append(f"{where} must be an object")
                continue
            if tier != "normal" and agent.get("cwd") and not (folder / str(tier)).is_dir():
                problems.append(f"{where}: no such tier folder: {folder / str(tier)}")
            problems.extend(f"{where}.{key}: a tier replaces only {', '.join(TIER_SETTING_KEYS)}"
                            for key in section if key not in TIER_SETTING_KEYS)
    return problems


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
    for problem in (_scan_extensions()[1] + _scan_page_origin()[1] + _scan_documents()[1]
                    + tier_setting_problems(cfg.get("agents"))):
        logger.warning("runtime check: %s", problem)
    missing = missing_ticket_checks()
    if missing:
        logger.warning("runtime check: the guard judges messages but not tickets; tickets are refused until these keys "
                       "are set: %s", ", ".join(missing))


# The configuration keys that hold the guard's commands for the tickets (`backend/tickets/ticket_checks.py`).
TICKET_CHECK_KEYS = ("TICKET_PLACE_CHECK", "TICKET_PLACES_CHECK", "TICKET_WRITE_CHECK", "TICKET_COVERS_CHECK",
                     "TICKET_READ_CHECK")


def _words(value: object) -> list[str]:
    """A command as the configuration gives it: a list of words, or no command (= empty) for anything else."""
    return value if isinstance(value, list) and all(isinstance(word, str) for word in value) else []


def missing_ticket_checks() -> list[str]:
    """The keys of the tickets' judgements that are left out on a machine whose messages the guard judges
    (`agent_message_check`). Empty on a machine without it, where the tickets go unjudged as messages do."""
    cfg = get_config()
    if not _words(cfg.get("agent_message_check")):
        return []
    return [key.lower() for key in TICKET_CHECK_KEYS if not _words(cfg.get(key.lower()))]


# --- 旧 module-level 定数の遅延配信 (PEP 562) ---
# 旧来の定数名を `__getattr__` で、 読まれた時に config を引いて返す。 読むたびに作るので、
# 使う側は `_config.AGENTS` のように使う所で読む (= 頭で import すると写しになる)。 lookup ごとに
# get_config() を呼ぶが、 内側で lru_cache されているので I/O は 1 回。
def __getattr__(name: str) -> Any:  # noqa: PLR0911
    cfg = get_config()
    if name == "AGENTS":
        return cfg.get("agents") or {}
    if name == "ACCOUNTS":
        return _accounts()
    if name == "CLAUDE_PROJECTS_DIRS":
        return _projects_dirs_from_accounts(_accounts())
    if name == "UPLOADS_TMP":
        return Path(cfg.get("uploads_tmp", str(UPLOADS_TMP_DIR))).expanduser()
    if name == "CLAUDE_PATH":
        return cfg.get("claude_path")
    if name in ("AGENT_MESSAGE_CHECK", "AGENT_MESSAGE_OPERATOR_CHECK", "AGENT_MESSAGE_SENDER_CHECK", "LINEAGE_HOOK",
                *TICKET_CHECK_KEYS):
        return _words(cfg.get(name.lower()))
    if name == "MACHINE_NAME":
        # The name the ids of the tickets this machine opens begin with (`backend/tickets/`).
        named = cfg.get("machine_name")
        return named.strip() if isinstance(named, str) and named.strip() else socket.gethostname().split(".")[0]
    if name == "AGENT_MESSAGE_PEERS":
        return _agent_message_peers(cfg.get("agent_message_peers"))
    if name == "CHILD_SESSIONS_MAX":
        # 1 つのタブが同時に持てる子のタブの数。 `None` = 上限なし (= 鍵が無い・`null`・読めない値)。 数を書いた人
        # (= 0 以上の整数) の意思だけが上限として効く。
        limit = cfg.get("child_sessions_max")
        return limit if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0 else None
    if name == "CORS_ALLOW_ORIGINS":
        return cfg.get("cors_allow_origins", [])
    if name == "RATE_LIMITS_LOG_PATH":
        return cfg.get("rate_limits_log") or (str(RATE_LIMITS_LOG_DEFAULT) if RATE_LIMITS_LOG_DEFAULT else "")
    if name == "TMUX_SESSION_MAP_DIR":
        return cfg.get("tmux_session_map_dir", "")
    if name == "VAPID_SUB":
        return cfg.get("vapid_sub", "mailto:admin@example.com")
    if name == "NOTIFICATION_TITLE_DEFAULT":
        return cfg.get("notification_title", "Notification")
    if name == "DEVICE_SCREEN":
        return cfg.get("device_screen")
    if name == "VOICE_CALL_GAIN_DB":
        gain = cfg.get("voice_call_gain_db", 0)
        return float(gain) if isinstance(gain, (int, float)) and not isinstance(gain, bool) else 0.0
    raise AttributeError(f"module 'backend._common.config' has no attribute {name!r}")
