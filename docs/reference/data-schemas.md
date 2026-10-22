# Data schemas (= `backend/data/*.json` + `backend/secrets/*.json` 真値)

backend が runtime に持つ JSON ファイルの schema を一括宣言する。 backend 再起動 / kickstart / 移送の際に **物理 backup すべき範囲** の真値でもある。

> 真値は dataclass / 実装 = `backend/_common/state.py::SessionDef` / `backend/jsonl/history.py` / `backend/jsonl/jsonl_watcher.py` / `backend/push/push.py`。 本 doc は **「backup 範囲を機械的に判断するための形式宣言」**。 実装が変わったら本 doc も同 PR で同期する。

## backup 必須範囲 (= 一覧)

| file | 物理 backup 必須? | 復元可能性 |
|---|---|---|
| `backend/data/session_meta.json` | **YES** (= 真値、 損失で全タブ消失) | jsonl_bindings + session_history から部分再構築可、 ただし title / notify_mode / parent_id は失われる |
| `backend/data/jsonl_bindings.json` | YES (= 真値、 損失で chat 表示できなくなる) | claude jsonl ファイル名 (= claude_sid) から逆引き可能だが手作業重い |
| `backend/data/session_history.json` | YES (= restart 復旧の唯一の手段) | 復元不可 (= 各 restart の直前 claude_sid を記録、 外部から再構築不能) |
| `backend/data/subscriptions.json` | YES (= 損失で Web Push 全消失) | クライアント側で「通知を有効にする」 再実行で復活可能だが iOS は再ホーム画面追加が必要なケースあり |
| `backend/secrets/vapid.json` | **YES** (= 鍵ペア、 損失で全 push subscription が無効化) | 復元不可 (= 新鍵生成すると全 client の subscription が `applicationServerKey` 不一致で reject される) |
| `backend/config.json` | YES (= 個人 cwd / launch_alias / accounts) | 復元可能だが手作業 |

backup 先 = 同 PC の別 path (= `$AGENT_PLATFORM_ROOT/state/claude-pwa-client/backups/` 等)、 backend dir 直下に置くと service 自身が誤読する事故源 (= 同 dir 内に `session_meta.json.<suffix>` 等の別名 backup を置くと service 起動時に snapshot として誤読されるパターンが存在する)。

## `backend/data/session_meta.json`

**形式**: `list[SessionDef dict]` (= `SessionDef.to_dict()` の出力)。 順序が UI ドロワーの並び順を直接決める。

**writer**: `backend/_common/state.py::save_sessions_meta()` (= `atomic_write_text` 経由)。 register_session / unregister_session / rename_session / set_notify_mode / demote_fork_to_normal / parent_id 操作の全 mutation で呼ばれる。

**真値 dataclass**: `backend/_common/state.py::SessionDef` (line 82-)

| field | 型 | 必須? | 説明 |
|---|---|---|---|
| `id` | str | YES | `ses_<12 hex>` 形式の PWA session ID。 backend / frontend / jsonl_bindings の真キー |
| `agent_id` | str | YES | `config.json::agents` の key (= 起動 cwd + launch_alias 解決) |
| `title` | str | YES | UI ドロワー / topbar 表示名 |
| `created_at` | int | YES | unix 秒 (= 作成時刻) |
| `notify_mode` | str | NO (default `"both"`) | `both` / `banner` / `off` (= Web Push の音 / バナー / 無効) |
| `parent_id` | str? | NO | fork 元か、 子のタブを立てた親の PWA session ID (= ドロワーで親の下にインデント表示)、 通常タブは null |
| `resume_session_id` | str? | NO | fork タブが初回 spawn で `claude --resume <id>` に使う claude session ID、 通常タブ + restart 後は null |
| `account_id` | str? | NO | `config.json::accounts` の key (= 起動 env を差し替え)、 null = personal 相当 |
| `child` | bool | NO (default `false`) | 子のタブ (= 別のタブの Claude が `POST /sessions/<親>/children` で立てたタブ) か。 親は `parent_id` |

`GET /sessions` の各行はこの物に **`tier`** を足して返します (= そのタブのエージェントが起動した階層。 エージェントの
プロセスが持つ環境変数 `AGENT_TIER` と同じ値で、 分からないタブは `null`)。 `tier` は `session_meta.json` には保存せず、
backend が claude のプロセスを見つけた時に読み直します (= 画面の一覧は、 口座の隣に階層の最後の名前を出します)。

## `backend/data/jsonl_bindings.json`

**形式**: `dict[pwa_sid, BindingInfo]`。 PWA session ID → 現在 active な claude jsonl ファイルへの bind。

**writer**: `backend/jsonl/jsonl_watcher.py::confirm_bind` / `unregister` / `prune_dead_bindings` (= 実際の書き出しは `_save_bindings`)。 hook 経由で `SessionStart` event が来ると bind が確定する。

**寿命**: 実体の JSONL が消えた entry は保持しない。 起動時は `_load_bindings` が復元せず、 稼働中は `prune_dead_bindings` が落とす (= `list_bindings` が返す前に呼ぶので、 読み手が受け取る binding は必ず実体を持つ)。 backup から戻す時も、 JSONL 本体が無い entry は復元されず消える。

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

**復旧 endpoint**: `GET /sessions/<pwa_sid>/history` (= `troubleshooting/troubleshoot.md § セッション復旧` 参照)。

## `backend/data/subscriptions.json`

**形式**: `list[Subscription dict]`。 W3C Push API の `PushSubscription.toJSON()` 互換。

**writer**: `backend/push/push.py::_save_subscriptions` (= POST /subscribe / DELETE /subscribe / `_atomic_remove_dead_subscriptions` 経由)。

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

## `~/.claude-pwa-client/favorites.txt`

お気に入り (= ⭐) の一覧。 **backend の状態ではなく利用者の物** なので、 置き場は repo の外 (= `~/.claude-pwa-client/`。
環境変数 `CPC_USER_DIR` で変えられる)。 画面は `GET` / `POST` / `DELETE /favorites` から読み書きし、 エージェントは
file を直に書く。 各タブのエージェントには、 この file の path が環境変数 `PWA_FAVORITES` で渡る。

**形式**: テキスト、 1 行に 1 path (= `~/...` か絶対 path)。

```
~/sample/design/overview.md
~/sample/project-a
```

- 登録は末尾に 1 行足すだけ (= `echo '~/sample/notes.md' >> "$PWA_FAVORITES"`)。 画面には、 次に ⭐ かファイルツリーを開いた時に出る
- file に持つのは path だけ。 フォルダかどうかと表示名は、 backend が読むたびに実物から導く
- 同じ path の行が 2 つ在っても一覧では 1 件。 path として読めない行 (= 空行、 メモ書き) は一覧に出ず、 画面から足す・外す操作でも消えない
- 消えた file を指す行も一覧に残る (= 外すのは利用者)

**writer**: `backend/routes/favorites.py` (= `atomic_write_text` 経由) と、 エージェント / 利用者の手書き。

backup: 任意 (= 失っても、 もう一度 ⭐ を付け直せば戻る)。

以前の版はこの一覧を各ブラウザの localStorage (= `cpc.fileTree.favorites`) に持っていた。 残っている分は、 その
ブラウザで画面を開いた最初の 1 回で host の一覧へ足され、 localStorage の側は消える。

## `<階層の folder>/pages/<タブの id>/memo.md`

タブごとのメモ (= 📋)。 置き場は **そのタブのエージェントの folder の中** です。 階層の folder は、
エージェントの folder (= `config.json` の `agents.<id>.cwd`) にそのタブの階層を足した所です
(= 階層は、 エージェントを起動する側が環境変数 `AGENT_TIER` でエージェントに渡す値で、 `normal` なら足さず、
`projects/<名前>` ならその下)。 階層が分からないタブは `normal` と同じ扱いです。 画面は
`GET` / `PUT /sessions/{sid}/note` から読み書きし、 そのタブのエージェントは file を直に書きます。 各タブの
エージェントには、 自分のタブの file の path が環境変数 `PWA_NOTE` で渡ります。

**形式**: markdown のテキスト 1 本。 画面は markdown のファイルと同じ描き方で出し (= 書いてある path はタップで開く)、 長くても畳まない。 段落の改行と空白は書いたとおりに残す (= 改行は改行のまま、 行頭の空白と続く空白は詰めない。 字は等幅ではないので、 桁を正確に揃えたい木や表はコードの囲み ``` に入れる)。

- 同じ `pages/<タブの id>/` には、 そのタブの他のページを置けます。 `index.html` は、 そのタブのトップページです
- メモが無いタブを開くと空で出ます。 メモの雛形は backend も書きません (= 書くのはエージェントと利用者です)
- **トップページは backend が作ります**。 タブの階層を記録した時 (= タブを立てた時、 backend の起動時、 会話の開始の知らせを受けた時) に、 `index.html` が無ければ、 `<エージェントの folder>/pages/_template-tab/index.html` (= 雛形。 階層ごとではなくエージェントに 1 つ) を写して作ります。 雛形の `{{title}}` はタブの題に、 `{{tier}}` は階層 (= `normal` や `projects/<名前>`) に置き換わります (= HTML として escape。 他の文字はそのまま)。 雛形が無いエージェントでは何もせず、 既に在るページには触りません
- 📋 の画面は、 メモの本文とは別の固定の行で、 そのタブのトップページへのリンクを出します (= `GET /sessions/{sid}/note` の `page`。 ページがまだ無ければ `null` で、 行は出ません)
- 空にしたメモ (= 画面の「リセット」、 か空文字の `PUT`) は file ごと消える
- エージェントが書いた分は、 メモを開いたままでも、 そのタブの会話が進んだ時に読み直される
- 上限は 1MB (= `/file` と同じ)
- タブを消しても、 メモは消えません (= エージェントの folder の記録として残ります)
- 前の版は `<根>/state/claude-pwa-client/notes/<タブの id>.md` (根を渡さない時は `~/.claude-pwa-client/notes/`) に置いていました。 backend は起動のたびに、 そこに残っているメモを今の置き場へ移します (= 移した先に既にメモが在る時は移さず残し、 backend の記録に 1 行出します)。 前の置き場の file が symlink の時は、 指す先の `<folder>/notes/<タブの id>.md` を同じ folder の `pages/<タブの id>/memo.md` へ移します

**writer**: `backend/routes/notes.py` (= `atomic_write_text` 経由) と、 そのタブのエージェント。 `index.html` の writer は `backend/terminal/tab_page.py` (= 最初の 1 回だけ) と、 そのタブのエージェント / 利用者。

backup: 任意 (= エージェントの folder の記録なので、 その folder の持ち主の方針に従う)。

## `~/.claude-pwa-client/page-store/<hash>.json`

設定の `page_origin` の folder のページが置く保存箱 (= ページ 1 つに 1 つ。 [config.md](config.md) の `page_origin`)。
ページはその port の `GET` / `PUT /.store/<ページの path>` から読み書きする。 **利用者の物** なので、 置き場は repo の外。

**形式**: ページが置いた JSON をそのまま 1 本。 名前はページの実体の絶対 path (= symlink を辿った後) の sha256。
ページを動かす・名前を変えると、 前の箱は読まれなくなる (= 消えはしない)。

- 上限は 1MB (= `/file` と同じ)
- 書き込みは丸ごとの置き換え。 `If-Match` を付けた書き込みは、 読んだ後に別の画面が書いていれば断られる

**writer**: `backend/routes/files.py` の `put_store` (= tmp に書いて `os.replace`)。

backup: ページの持ち主の判断 (= チェックの記録のような、 その場でしか作れない物を置くなら取る)。

## 関連

- backend 再起動 / kickstart 手順は `../troubleshooting/sunshine.md` / LaunchAgent 関連は `../setup/path-a-chat.md § backend を常駐起動する`
- 上記 backup 対象は `backend/` 配下を `find -type f` で総ざらいしてから決める (= 既知 file だけで safety net 張ったつもりになるのは事故源、 service dir 全 file を視野に)
