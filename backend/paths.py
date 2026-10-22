"""path resolution single source of truth.

このモジュールが backend 配下の全 file path を一括宣言する。 各 module で
`Path(__file__).parent[.parent]` を書くと、 サブパッケージ化や file 移動の
たびに段数が狂って "vapid.json が見つからない" 系の事故 (2026-06-15 観測)
を再発する。 新規 path 追加 / 移動はここを起点に。

置き場の決め方 (= 強い順):

1. 個別の環境変数 (`CPC_DATA_DIR` / `CPC_LOGS_DIR` / `CPC_CONFIG_PATH` / `CPC_SECRETS_DIR` / `CPC_USER_DIR`)
2. 器の根 (`AGENT_PLATFORM_ROOT`): `<根>/<役割>/claude-pwa-client/` の下 (= 役割は config / secrets / state / cache)
3. 今までの既定 (= 下の「根が無い時」)

テスト mode (= playwright webServer) は個別の環境変数で本番 data と隔離する。

根が在る時:

```
<AGENT_PLATFORM_ROOT>/
├── config/claude-pwa-client/
│   ├── config.json        (人が書く設定)
│   └── favorites.txt      (⭐ の一覧)
├── secrets/claude-pwa-client/
│   └── vapid.json         (鍵、 perm 700)
├── state/claude-pwa-client/
│   ├── data/              (運用 state。 session_meta.json / subscriptions.json / jsonl_bindings.json)
│   ├── logs/              (rotating log)
│   ├── backups/           (更新前の控え。 backend は書かず、 更新の手順が置く)
│   ├── notes/<tab id>.md  (where earlier versions kept memos; moved to `<tier folder>/pages/<tab id>/memo.md` at startup)
│   ├── page-store/        (ページの保存箱)
│   └── uploads/           (添付の一時置き場。 `config.json` の `uploads_tmp` が決めた時はそちら)
├── cache/claude-pwa-client/
│   └── document-cache/    (資料を頁の画像に変えた物の控え)
└── state/statusline/rate-limits.jsonl   (使用量の記録。 `config.json` の `rate_limits_log` が無い時の既定)
```

根が無い時:

```
<REPO_ROOT>/
├── backend/
│   ├── data/              (運用 state、 git ignore)
│   ├── secrets/           (秘密鍵、 git ignore、 perm 700)
│   │   └── vapid.json
│   └── config.json        (個人設定、 git ignore、 backend 直下のまま)
├── logs/                  (rotating log、 git ignore)
└── frontend/dist/         (ビルド成果物)

~/.claude-pwa-client/      (利用者とエージェントが書く物。 repo の外。 `CPC_USER_DIR` で動かせる)
├── favorites.txt
├── notes/<tab id>.md      (where earlier versions kept memos; moved at startup)
├── page-store/
├── document-cache/
├── backups/
└── uploads/tmp/
```

`data/` は backend だけが読み書きする運用 state。 利用者とそのエージェントが直に書く物は
repo の外に置く (= エージェントの書き込み先を作業中の repo に限る類の守りが在る環境でも、
どの repo にも属さない場所なら書ける。 checkout の中に置くと、 その守りの下のエージェントは足せない)。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

TOOL_NAME = "claude-pwa-client"


def _env_dir(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else None


def _env_path(name: str, default: Path) -> Path:
    return _env_dir(name) or default


PLATFORM_ROOT = _env_dir("AGENT_PLATFORM_ROOT")
LEGACY_USER_DIR = Path.home() / ".claude-pwa-client"
_USER_DIR_OVERRIDE = _env_dir("CPC_USER_DIR")


def _platform_path(role: str, *parts: str, legacy: Path) -> Path:
    """器の根の下の `<役割>/claude-pwa-client/<parts>`。 根が無ければ `legacy`。"""
    if PLATFORM_ROOT is None:
        return legacy
    return PLATFORM_ROOT.joinpath(role, TOOL_NAME, *parts)


def _user_path(role: str, platform_name: str, legacy_name: str) -> Path:
    """利用者とエージェントが書く物の置き場。 `CPC_USER_DIR` が在ればその下、 無ければ根の下、 それも無ければ `~/.claude-pwa-client/`。"""
    if _USER_DIR_OVERRIDE is not None:
        return _USER_DIR_OVERRIDE / legacy_name
    return _platform_path(role, platform_name, legacy=LEGACY_USER_DIR / legacy_name)


DATA_DIR = _env_path("CPC_DATA_DIR", _platform_path("state", "data", legacy=BACKEND_DIR / "data"))
SECRETS_DIR = _env_path("CPC_SECRETS_DIR", _platform_path("secrets", legacy=BACKEND_DIR / "secrets"))
LOGS_DIR = _env_path("CPC_LOGS_DIR", _platform_path("state", "logs", legacy=REPO_ROOT / "logs"))
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

CONFIG_PATH = _env_path("CPC_CONFIG_PATH", _platform_path("config", "config.json", legacy=BACKEND_DIR / "config.json"))
SESSION_META_PATH = DATA_DIR / "session_meta.json"
SUBSCRIPTIONS_PATH = DATA_DIR / "subscriptions.json"
JSONL_BINDINGS_PATH = DATA_DIR / "jsonl_bindings.json"
# pwa_sid → 直近 N (= 既定 3) 件の claude_sid 履歴。 restart (= セッション終了ボタン) で
# kill する直前にその時点の claude_sid を記録 → binding が事故で消えた / 古い backup に
# 戻った時の復旧源として使う。 N 件で打ち切るので無限肥大しない。
SESSION_HISTORY_PATH = DATA_DIR / "session_history.json"
VAPID_PATH = SECRETS_DIR / "vapid.json"

# お気に入り: 1 行に 1 path のテキスト (= エージェントは 1 行足すだけで登録できる)
FAVORITES_PATH = _user_path("config", "favorites.txt", "favorites.txt")
# Where earlier versions kept each tab's memo (`<tab id>.md`). A memo now lives at
# `<tier folder>/pages/<tab id>/memo.md` (`backend/terminal/tab_memo.py`); what is left here moves there at startup.
LEGACY_NOTES_DIR = _user_path("state", "notes", "notes")
# ページの origin の保存箱 (= ページごとに JSON を 1 つ。 `backend/routes/files.py` の `/.store/`)
PAGE_STORE_DIR = _user_path("state", "page-store", "page-store")
# 添付の一時置き場の既定 (= `config.json` の `uploads_tmp` が在ればそちら)
UPLOADS_TMP_DIR = _user_path("state", "uploads", "uploads/tmp")
# 更新前の控えの置き場 (= backend は書かない。 更新の手順が置く)
BACKUPS_DIR = _user_path("state", "backups", "backups")
# 資料 (= pdf・Office・tif) を頁の画像に変えた物の控えの既定 (= `config.json` の `documents.cache_dir` が在ればそちら)
DOCUMENT_CACHE_DIR = _user_path("cache", "document-cache", "document-cache")
# 使用量の記録 (= statusline が書く)。 根が在る時だけの既定で、 `config.json` の `rate_limits_log` が在ればそちら
RATE_LIMITS_LOG_DEFAULT = (
    PLATFORM_ROOT / "state" / "statusline" / "rate-limits.jsonl" if PLATFORM_ROOT is not None else None
)


def ensure_runtime_dirs() -> None:
    """起動時に呼ぶ。 data/ secrets/ logs/ と ⭐ の置き場を 必要なら作る。 SECRETS_DIR は
    perm 700 で作り、 既存なら chmod で 700 に揃える (個人 Mac 1 ユーザ運用
    前提だが、 同マシンに別ユーザがいる場合の保険)。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(stat.S_IRWXU)
    FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()
