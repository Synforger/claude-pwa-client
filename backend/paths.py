"""path resolution single source of truth.

このモジュールが backend 配下の全 file path を一括宣言する。 各 module で
`Path(__file__).parent[.parent]` を書くと、 サブパッケージ化や file 移動の
たびに段数が狂って "vapid.json が見つからない" 系の事故 (2026-06-15 観測)
を再発する。 新規 path 追加 / 移動はここを起点に。

レイアウト:

```
<REPO_ROOT>/
├── backend/
│   ├── data/          (運用 state、 git ignore)
│   │   ├── session_meta.json
│   │   ├── subscriptions.json
│   │   └── jsonl_bindings.json
│   ├── secrets/       (秘密鍵、 git ignore、 perm 700)
│   │   └── vapid.json
│   ├── config.json    (個人設定、 git ignore、 backend 直下のまま)
│   └── ...
├── logs/              (rotating log、 git ignore)
└── frontend/
    └── dist/          (ビルド成果物)

~/.claude-pwa-client/  (利用者とエージェントが書く物。 repo の外)
├── favorites.txt
├── notes/<タブの id>.md  (タブごとのメモ。 タブを消すと消える)
└── uploads/tmp/       (添付の一時置き場。 既定がこの下で、 場所は config.json の `uploads_tmp` が決める)
```

`backend/data/` は backend だけが読み書きする運用 state。 利用者とそのエージェントが直に書く物は
repo の外の USER_DIR に置く (= エージェントの書き込み先を作業中の repo に限る類の守りが在る環境でも、
どの repo にも属さない場所なら書ける。 checkout の中に置くと、 その守りの下のエージェントは足せない)。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


def _env_path(name: str, default: Path) -> Path:
    # env override をここに集中させる。 test mode (= playwright webServer) は
    # CPC_DATA_DIR / CPC_LOGS_DIR / CPC_CONFIG_PATH / CPC_SECRETS_DIR / CPC_USER_DIR を投げて
    # 本番 data と隔離する。 未設定なら従来の hardcoded path。
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


DATA_DIR = _env_path("CPC_DATA_DIR", BACKEND_DIR / "data")
SECRETS_DIR = _env_path("CPC_SECRETS_DIR", BACKEND_DIR / "secrets")
LOGS_DIR = _env_path("CPC_LOGS_DIR", REPO_ROOT / "logs")
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

CONFIG_PATH = _env_path("CPC_CONFIG_PATH", BACKEND_DIR / "config.json")
SESSION_META_PATH = DATA_DIR / "session_meta.json"
SUBSCRIPTIONS_PATH = DATA_DIR / "subscriptions.json"
JSONL_BINDINGS_PATH = DATA_DIR / "jsonl_bindings.json"
# pwa_sid → 直近 N (= 既定 3) 件の claude_sid 履歴。 restart (= セッション終了ボタン) で
# kill する直前にその時点の claude_sid を記録 → binding が事故で消えた / 古い backup に
# 戻った時の復旧源として使う。 N 件で打ち切るので無限肥大しない。
SESSION_HISTORY_PATH = DATA_DIR / "session_history.json"
VAPID_PATH = SECRETS_DIR / "vapid.json"

# 利用者とエージェントが書く物の置き場 (= repo の外)。 画面は backend 経由で、 エージェントは file を直に書く。
USER_DIR = _env_path("CPC_USER_DIR", Path.home() / ".claude-pwa-client")
# お気に入り: 1 行に 1 path のテキスト (= エージェントは 1 行足すだけで登録できる)
FAVORITES_PATH = USER_DIR / "favorites.txt"
# タブごとのメモ: `<タブの id>.md` (= そのタブの物。 タブを消すと一緒に消える)
NOTES_DIR = USER_DIR / "notes"


def note_path(session_id: str) -> Path:
    """そのタブのメモの file。 id は backend が発行した物だけを渡す (= 区切りを含む id は置き場の外を指す)。"""
    if not session_id or Path(session_id).name != session_id:
        raise ValueError(f"not a session id: {session_id!r}")
    return NOTES_DIR / f"{session_id}.md"


def ensure_runtime_dirs() -> None:
    """起動時に呼ぶ。 data/ secrets/ logs/ と USER_DIR を 必要なら作る。 SECRETS_DIR は
    perm 700 で作り、 既存なら chmod で 700 に揃える (個人 Mac 1 ユーザ運用
    前提だが、 同マシンに別ユーザがいる場合の保険)。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(stat.S_IRWXU)
    USER_DIR.mkdir(parents=True, exist_ok=True)
    # エージェントが最初の 1 回から書けるよう、 メモの置き場も先に作る
    NOTES_DIR.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()
