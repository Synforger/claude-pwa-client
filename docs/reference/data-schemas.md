# Data schemas (= `backend/data/*.json` + `backend/secrets/*.json` 真値)

backend が runtime に持つ JSON ファイルの schema を一括宣言する。 backend 再起動 / kickstart / 移送の際に **物理 backup すべき範囲** の真値でもある (= 2026-06-29 session_meta.json 消失事故の根治、 詳細は `rules/always/standing-service-backup.md`)。

> 真値は dataclass / 実装 = `backend/state.py::SessionDef` / `backend/jsonl/history.py` / `backend/jsonl/watcher.py` / `backend/core/push.py`。 本 doc は **「backup 範囲を機械的に判断するための形式宣言」**。 実装が変わったら本 doc も同 PR で同期する。

## backup 必須範囲 (= 一覧)

| file | 物理 backup 必須? | 復元可能性 |
|---|---|---|
| `backend/data/session_meta.json` | **YES** (= 真値、 損失で全タブ消失) | jsonl_bindings + session_history から部分再構築可、 ただし title / notify_mode / parent_id は失われる |
| `backend/data/jsonl_bindings.json` | YES (= 真値、 損失で chat 表示できなくなる) | claude jsonl ファイル名 (= claude_sid) から逆引き可能だが手作業重い |
| `backend/data/session_history.json` | YES (= restart 復旧の唯一の手段) | 復元不可 (= 各 restart の直前 claude_sid を記録、 外部から再構築不能) |
| `backend/data/subscriptions.json` | YES (= 損失で Web Push 全消失) | クライアント側で「通知を有効にする」 再実行で復活可能だが iOS は再ホーム画面追加が必要なケースあり |
| `backend/secrets/vapid.json` | **YES** (= 鍵ペア、 損失で全 push subscription が無効化) | 復元不可 (= 新鍵生成すると全 client の subscription が `applicationServerKey` 不一致で reject される) |
| `backend/config.json` | YES (= 個人 cwd / launch_alias / accounts) | 復元可能だが手作業 |

backup 先 = 同 PC の別 path (= `~/backups/<service>/<date>/` 等)、 backend dir 直下に置くと service 自身が誤読する事故源 (= 同 dir 内に `session_meta.json.<suffix>` 等の別名 backup を置くと service 起動時に snapshot として誤読されるパターンが存在する)。

## `backend/data/session_meta.json`

**形式**: `list[SessionDef dict]` (= `SessionDef.to_dict()` の出力)。 順序が UI ドロワーの並び順を直接決める。

**writer**: `backend/state.py::save_sessions_meta()` (= `atomic_write_text` 経由)。 register_session / unregister_session / rename_session / set_notify_mode / demote_fork_to_normal / parent_id 操作の全 mutation で呼ばれる。

**真値 dataclass**: `backend/state.py::SessionDef` (line 82-)

| field | 型 | 必須? | 説明 |
|---|---|---|---|
| `id` | str | YES | `ses_<12 hex>` 形式の PWA session ID。 backend / frontend / jsonl_bindings の真キー |
| `agent_id` | str | YES | `config.json::agents` の key (= 起動 cwd + launch_alias 解決) |
| `title` | str | YES | UI ドロワー / topbar 表示名 |
| `created_at` | int | YES | unix 秒 (= 作成時刻) |
| `notify_mode` | str | NO (default `"both"`) | `both` / `banner` / `off` (= Web Push の音 / バナー / 無効) |
| `parent_id` | str? | NO | fork 元 PWA session ID (= ドロワーで親の下にインデント表示)、 通常タブは null |
| `resume_session_id` | str? | NO | fork タブが初回 spawn で `claude --resume <id>` に使う claude session ID、 通常タブ + restart 後は null |
| `account_id` | str? | NO | `config.json::accounts` の key (= 起動 env を差し替え)、 null = personal 相当 |

## `backend/data/jsonl_bindings.json`

**形式**: `dict[pwa_sid, BindingInfo]`。 PWA session ID → 現在 active な claude jsonl ファイルへの bind。

**writer**: `backend/jsonl/watcher.py::confirm_bind` / `unregister` / `_persist`。 hook 経由で `SessionStart` event が来ると bind が確定する。

| field | 型 | 説明 |
|---|---|---|
| `tmux_sid` | str | tmux session 名 (= `pwa-<pwa_sid>` パターン) |
| `claude_pid` | int | 起動中 claude プロセスの PID |
| `claude_cwd` | str | claude が動いてる cwd (= `agents[*].cwd` と一致) |
| `start_time` | float | unix 秒 (= bind 確定時刻) |
| `jsonl_path` | str | `~/.claude/projects/<cwd-hash>/<claude_sid>.jsonl` の絶対パス。 chat tail の入力 |
| `confirmed` | bool | hook が `SessionStart` を送ってきたかどうか (= false なら autoresume 経路で消える可能性あり) |

## `backend/data/session_history.json`

**形式**: `dict[pwa_sid, list[HistoryEntry]]`。 各 PWA session の restart 履歴を最新順で最大 3 件保持。

**writer**: `backend/jsonl/history.py::record_end`。 `POST /sessions/<sid>/restart` で kill する直前に呼ばれる。 同一 claude_sid の連投は dedup、 4 件目以降は古い方から落ちる。

**HistoryEntry**:

| field | 型 | 説明 |
|---|---|---|
| `claude_sid` | str | restart 直前まで動いてた claude session ID (= jsonl ファイル名 stem) |
| `ended_at` | int | unix 秒 |
| `jsonl_path` | str | restart 直前の jsonl 絶対パス。 復旧時に `claude --resume <claude_sid>` で開く |

**復旧 endpoint**: `GET /sessions/<pwa_sid>/history` (= `ops/troubleshoot.md § セッション復旧` 参照)。

## `backend/data/subscriptions.json`

**形式**: `list[Subscription dict]`。 W3C Push API の `PushSubscription.toJSON()` 互換。

**writer**: `backend/core/push.py::_save_subscriptions` (= POST /subscribe / DELETE /subscribe / `_atomic_remove_dead_subscriptions` 経由)。

| field | 型 | 説明 |
|---|---|---|
| `endpoint` | str | push service の URL (= browser 固有、 例 `https://web.push.apple.com/...`) |
| `keys` | dict | `{p256dh: <ECDH 公開鍵 base64>, auth: <auth secret base64>}` (= ペイロード暗号化用) |

dedup キー = `endpoint`。 backend は 410/404 応答で dead subscription を staged commit pattern で消す (= 2026-06-21、 backend-F-47)。

## `backend/secrets/vapid.json`

**形式**: VAPID 鍵ペア (= W3C Push API の applicationServerKey + 署名鍵)。

**generator**: `python -m backend.cli.gen_vapid` (= 1 度だけ生成、 `--force` で再生成)。 詳細は `reference/config.md § VAPID 鍵`。

| field | 型 | 説明 |
|---|---|---|
| `private_pem` | str | pywebpush に渡す PEM 形式の private key |
| `public_key` | str | フロント `applicationServerKey` 用の base64url エンコード済 public key |

> **再生成は禁忌**: 鍵を作り直すと既存 `subscriptions.json` の全 entry が `applicationServerKey` 不一致で 410 / silent drop となり、 全 client で「通知を有効にする」 を再実行しないと復活しない。 backup を取らずに削除 / `--force` 再生成しないこと。

## 関連

- backend 再起動 / kickstart 手順は `../ops/sunshine.md` / LaunchAgent 関連は `../setup/path-a-chat.md § backend を常駐起動する`
- 上記 backup 対象は `backend/` 配下を `find -type f` で総ざらいしてから決める (= 既知 file だけで safety net 張ったつもりになるのは事故源、 service dir 全 file を視野に)
