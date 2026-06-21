"""アプリ設定の読み込みと、複数モジュールから参照する定数。"""
import json
from pathlib import Path

from backend.paths import CONFIG_PATH

HOME = Path.home()

with open(CONFIG_PATH) as f:
    config = json.load(f)

# --- agent 定義 ---
AGENTS: dict = config["agents"]

# --- Claude OAuth プロファイル ("アカウント") 定義 ---
# 各タブが起動時にどの ~/.claude / ~/.claude-work を使うかを SessionDef.account_id で
# 指定し、 spawn 時に accounts[account_id].env を tmux env として注入する。 デフォルトは
# personal (= 通常の ~/.claude 経路 = env 空) のみ。 会社アカウントを使う場合は
# config.json で `accounts: {personal: {...}, work: {env: {CLAUDE_CONFIG_DIR: ...}}}`
# のように追加する。
ACCOUNTS: dict = config.get("accounts") or {"personal": {"display_name": "個人", "env": {}}}


def _projects_dirs_from_accounts() -> list[Path]:
    """ACCOUNTS の env.CLAUDE_CONFIG_DIR から projects ディレクトリ候補を集める。
    デフォルト `~/.claude/projects` は常に含める (= account_id=None 互換)。
    """
    dirs: list[Path] = [Path.home() / ".claude" / "projects"]
    for cfg in ACCOUNTS.values():
        env = (cfg or {}).get("env") or {}
        d = env.get("CLAUDE_CONFIG_DIR")
        if d:
            p = Path(d).expanduser() / "projects"
            if p not in dirs:
                dirs.append(p)
    return dirs


# 監視・検索対象の Claude projects ディレクトリ群。 personal (= 通常 ~/.claude/projects)
# に加えて、 ACCOUNTS で CLAUDE_CONFIG_DIR が指定されてれば ~/.claude-work/projects 等も
# 含む。 jsonl_watcher / maintenance / fork はこの list を走査して該当 dir を選ぶ。
CLAUDE_PROJECTS_DIRS: list[Path] = _projects_dirs_from_accounts()


def projects_dir_for_account(account_id: str | None) -> Path:
    """session の account_id から projects ディレクトリを返す。 該当が無ければ personal
    (= ~/.claude/projects) にフォールバック。
    """
    if account_id:
        env = (ACCOUNTS.get(account_id) or {}).get("env") or {}
        d = env.get("CLAUDE_CONFIG_DIR")
        if d:
            return Path(d).expanduser() / "projects"
    return Path.home() / ".claude" / "projects"

# --- ファイル系 ---
# uploads_tmp は config.json で上書き可能。
UPLOADS_TMP = Path(config.get("uploads_tmp", str(HOME / ".claude-pwa-client" / "uploads" / "tmp"))).expanduser()
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
FILE_SIZE_LIMIT = 1 * 1024 * 1024  # 1MB

# --- claude CLI ---
CLAUDE_PATH = config.get("claude_path")

# --- CORS ---
# CORS で許可するオリジン。 未設定 ( = config.json に cors_allow_origins キー無し) なら
# 空リストで CORS middleware を有効化しない、 つまり同一オリジン (= backend 配信の frontend)
# からのアクセスのみ通る (= 本番デフォルト)。 Vite dev server から叩く時は
# config.json で `["http://localhost:5173"]` 等を明示して dev 環境だけ開く。
CORS_ALLOW_ORIGINS: list = config.get("cors_allow_origins", [])

# --- 観測 ---
# Anthropic API レスポンス毎 (= ResultMessage 受信時) に shared rate-limit と usage を
# JSONL で永続化するファイル。 PWA 経由の token 消費 / 5h / 7d 使用率を時系列で観察する
# 用途。 path が空 / 未設定なら no-op (= backend は何も書かない)。
RATE_LIMITS_LOG_PATH = config.get("rate_limits_log", "")

# --- chat UI の JSONL 解決 ---
# statusline が「tmux session 名 → claude session id」 を 1 session = 1 ファイルで書き出す
# ディレクトリ。 複数タブが同じ cwd を共有しても JSONL を一意特定するのに使う。 未設定なら
# 最新 mtime の fallback だけで動く。
TMUX_SESSION_MAP_DIR: str = config.get("tmux_session_map_dir", "")

# --- Web Push 関連 ---
# VAPID claim の sub (連絡先)。デフォルトは汎用 mailto。
VAPID_SUB = config.get("vapid_sub", "mailto:admin@example.com")
# OS 通知のタイトル既定値。エージェント別は agents.<name>.notification_title で上書き。
NOTIFICATION_TITLE_DEFAULT = config.get("notification_title", "Notification")
