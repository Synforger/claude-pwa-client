# Streams (= SSE / WebSocket 経路 + event wire shape)

backend と frontend を繋ぐリアルタイム経路は **4 本の SSE + 2 本の WebSocket** の合計 6 経路に分かれる。 各経路は単一責任に切ってあり、 経路同士で重複した state を持たない (= 経路をまたいだ dual-driver で UI が振動する旧来バグの根治構造)。 本書は 6 経路の責任分担 + `/jsonl/stream/*` で流れる SSE event の wire shape を 1 ファイルで宣言する真値とする。

> sse-event-shape.md は本 file に統合 (= 2026-06-29、 docs 再編で真値分散排除)。 旧 path から飛ばしたい場合は本 file の § event wire shape を参照。

## 1 枚図

```
                                ┌────────────────────────────────────────┐
                                │ backend (= FastAPI、 単一プロセス)        │
                                │                                          │
   ┌─────────────────┐  SSE     │  /sessions/status/stream   ◀── 全 sid の  │
   │ useStatus       │ ◀────────┤    status_event (per sid) / shared       │
   │ (allStatus)     │          │    usage / rate-limits memoize           │
   └─────────────────┘          │                                          │
                                │                                          │
   ┌─────────────────┐  SSE     │  /sessions/overview/stream ◀── 全 sid の  │
   │ useSessions     │ ◀────────┤    busy / pending / last_seen / unread   │
   │ Overview        │          │    by OverviewBroadcaster (per-conn Ev)  │
   │ (loading[sid])  │          │                                          │
   └─────────────────┘          │                                          │
                                │                                          │
   ┌─────────────────┐  SSE     │  /jsonl/stream/{sid}        ◀── claude    │
   │ useChatStream   │ ◀────────┤    が書く JSONL を tail → events.py で    │
   │ (messages/sid)  │          │    processStreamEvent 入力に変換          │
   └─────────────────┘          │                                          │
                                │                                          │
   ┌─────────────────┐  SSE     │  /jsonl/stream/all          ◀── 全 sid を │
   │ useChatStreamAll│ ◀────────┤    1 接続で配信 (F-15)、 sid 別 offset    │
   │ (messages map)  │          │    map で per-sid 差分 tail               │
   └─────────────────┘          │                                          │
                                │                                          │
   ┌─────────────────┐  WS      │  /views/ws                  ◀── 視認中    │
   │ useViewsWs      │ ◀───────▶│    sid + Stop 意思を双方向に伝送          │
   │ (sendStopIntent)│          │    (TCP FIN で自動 stale 抹消)            │
   │                 │          │                                          │
   │                 │  WS      │  /ws/pty/{sid}              ◀── 「ターミ  │
   │ Terminal (xterm)│ ◀───────▶│    ナルを表示」 で attach、 xterm input   │
   │                 │          │    を tmux send-keys に転送、 PTY 出力を  │
   │                 │          │    xterm に流す                          │
   └─────────────────┘          └────────────────────────────────────────┘
```

## 1 表で責任分担

| 経路 | 種別 | backend 実装 | frontend consumer | payload | 接続パターン | 役割 |
|---|---|---|---|---|---|---|
| `/sessions/status/stream` | SSE | `backend/routes/overview.py::all_status_stream` | `frontend/src/features/status-bar/useStatus.js` | `{ <sid>: <AgentStatus dict>, ... }` 全 sid 分の status を 1 dict | mount 1 回張りっぱなし、 activeSid 変化で再接続しない | StatusBar (モデル / mode / 残予算 / 5h / 7d / ctx / 🔗 PR chip)、 pending_question 表示、 pending_plan 表示 |
| `/sessions/overview/stream` | SSE | `backend/routes/overview.py::sessions_overview_stream` | `frontend/src/features/session-drawer/useSessionsOverview.js` (`transport/sse-overview.js` singleton 経由) | `{ <sid>: { busy, pending, last_seen_at, unread_done }, ... }` | mount 1 回張りっぱなし、 全 client / 全タブで共有 | **停止ボタン (= `state/ephemeral.js::loading[sid]`) の唯一のソース**、 ドロワー一覧の青丸 (処理中) / 赤丸 (完了未読)、 未読 last_seen sync |
| `/jsonl/stream/{sid}` | SSE | `backend/jsonl/routes.py::jsonl_stream` | `frontend/src/features/chat/useChatStream.js` | `data: {<processStreamEvent event>}\n\n` (= 詳細は本 file § event wire shape) | activeSid 変化で再接続。 `?from=<offset>` で前回 byte offset 以降の完全行のみ流す (= 初回 replay 軽量化) | per-sid chat messages 配列の組み立て (= legacy 経路、 タブ切替で SSE 張り替え) |
| `/jsonl/stream/all` | SSE | `backend/jsonl/routes.py::jsonl_stream_all` (= W2-F15) | `frontend/src/features/chat/useChatStream.js` (= `?from=<sid>:<off>,...` 経路) | event の `sid` field で振り分け、 SSE id = `<sid>:<pos>` | mount 1 回張りっぱなし、 タブ切替で SSE 張り替えしない | 全 sid 1 接続版。 接続時に sessions_meta 全件に `ensure_pty_session_for` を sweep (= 新規タブ作成時の spawn trigger も兼ねる、 ただし接続継続中の新 sid は捕捉漏れがあるので POST /sessions 側でも ensure する。 2026-06-29 fix) |
| `/views/ws` | WebSocket | `backend/routes/overview.py::views_ws` | `frontend/src/features/push-notify/useViewsWs.js` | client → server: `{"sid": "ses_xxx"\|null}` (= 視認中 sid 更新) / `{"type":"stop","sid":"..."}` (= Stop 意思)。 server → client: 受信のみ (broadcast なし) | PWA visible 中だけ常時接続、 3 秒 reconnect。 接続切断 (= TCP FIN / iOS bg 化) で `views_by_conn` から自動削除 | (1) 通知抑制判定 (= `is_session_viewed(sid)` が真なら `broadcast_push` skip) (2) Stop ボタン (= HTTP POST だと race で busy=true 復活する経路を WS の TCP 保証で潰す) |
| `/ws/pty/{sid}` | WebSocket | `backend/terminal/routes.py::pty_socket` | `frontend/src/features/terminal/useTerminal.js` (= xterm.js + transport/ws-pty.js) | client → server: `{"type":"input","data":"..."}` (= tmux send-keys 転送) / `{"type":"resize", ...}`。 server → client: `{"type":"output","data":"..."}` (= PTY 出力 bytes) | viewMode='terminal' 切替時に attach、 切断中は backend が `session.output_queue` に backlog 蓄積 (drain on reconnect) | xterm.js の入出力経路。 chat view のみ使う場合は接続しない (= W2 後は POST /sessions / restart 経路で backend 側 PTY spawn が完結するので、 chat view 単独で claude 起動が走り切る) |

## 経路別の設計判断 (= なぜこの分け方か)

### `/sessions/status/stream`: 全 sid 1 接続

旧設計は sid 毎に `/status/{sid}/stream` を張り替えていた。 タブ切替のたびに SSE を旧 close → 新接続し、 iOS Safari の 1-3 秒の TCP 確立コストで「タブ切替したのに status が出るのが遅い」 体感だった。 全 sid を 1 接続で配信に変更 (= overview と同パターン) し、 タブ切替で SSE 張り替え不要 → 切替コスト 0。 各 client は受信 payload から自分の activeSid 分を取り出すだけ。

`StreamState.status_event` (per sid `asyncio.Event`) を起点に、 hooks / jsonl 経路で変化があったら `set()` → SSE 接続側が起きて全 sid snapshot を yield → `clear()`。 接続ごとの diff 配信 (= F-09) で snapshot 不変なら data 行を yield しない。 keep-alive は SSE comment 行のみ (= `:\n\n`、 F-10) で全 sid JSON を毎 20s 流す無駄を排除。 rate-limits は 1 秒 cache で接続数 × notify 回 read を縮める (= F-56)。

### `/sessions/overview/stream`: backend 権威 busy の唯一のソース

停止ボタン (= `loading[sid]`、 真値は `state/ephemeral.js`) は backend が JSONL の `stop_reason` から確定的に算出した `StreamState.busy` ただ 1 つ。 chat SSE (`useChatStream`) も `loading` を一切触らない (= 旧 useState 経路は J-9 で `state/ephemeral.js` singleton に統合済)。 旧来は「per-tab assistant/result で loading を上下する」 と「overview で上書き」 の dual-driver になっており、 イベント取りこぼし / 再接続 / 複数デバイスで振動していた (= 2026-06-03 根本治療)。

overview は毎回フル snapshot なので、 取りこぼし / 再接続 / 複数デバイスでも次の snapshot で必ず正しい状態に収束する (= reconcile-on-snapshot)。 楽観意図 (`optimisticRef`) は送信 / 停止 直後の逆向き古 snapshot から UI を保護する短期ウィンドウのみで、 1500ms タイマー駆動は撤去し snapshot 駆動の event ベースに揃えた。

fan-out は `OverviewBroadcaster` (= per-connection `asyncio.Event` を broadcaster が一括 `notify`)。 旧実装の単一 `Event` 共有では 1 接続の generator が `clear()` した瞬間に他接続の `wait` が起きそこねて push を落としていた。

### `/jsonl/stream/{sid}` と `/jsonl/stream/all`: 入出力分離の「出力」 側

claude を PTY/TUI 経路で動かすと、 全 turn が `~/.claude/projects/<cwd-hash>/<claude_session_id>.jsonl` に追記される。 これを backend が tail し `jsonl_line_to_events` で `processStreamEvent` 入力形式に変換 → SSE で配信することで、 proxy / SDK / `-p` を一切使わず chat UI を再構成できる (= subscription 枠で動く、 軽い)。

per-sid (`/jsonl/stream/{sid}`) はタブ切替で接続張り替え。 全 sid (`/jsonl/stream/all`、 W2-F15) は 1 接続で全タブの差分を受けて localStorage の offset map で位置を track する。 接続時に sessions_meta の全 sid に `ensure_pty_session_for` を sweep するので、 接続中に既に存在する sid は chat view を開いただけで claude が立ち上がる。 ただし接続継続中に POST /sessions で新規追加された sid は sweep 漏れるので、 `create_session` 側でも `ensure_pty_session_for` を呼ぶ (= 2026-06-29 race 修正)。

入力 (= キー送信) は `/ws/pty/{sid}` + `/pty/{sid}/send` 系。 **出力 = JSONL tail / 入力 = キー送出** を strict に分離することで、 claude CLI が書く真値だけが UI に出る (= backend 中央で偽 event を合成しない)。

### `/views/ws`: 視認シグナル = 接続生存

「今どの sid を見ているか」 を realtime に backend へ伝える。 接続中の間 sid を保持し、 `broadcast_push` の `is_session_viewed(sid)` 判定に使う。 TCP FIN / iOS bg 化での socket 切断 = 視認終了として自動削除されるので、 **stale 概念が構造的に存在しない** (= 過去に visibility state を backend が持ったときの「通知が永久抑制される」 バグの再発防止)。

Stop ボタン経路も WS で通す。 HTTP POST 経路だと送信失敗 race で overview SSE が busy=true を流し停止ボタンが復活していた。 WS 接続中なら TCP 保証で届く、 切断中 (= PWA が見えてない) なら stop は押せないので何もしない、 で正当性を担保する。

可視タブでの通知抑制は **SW** (`frontend/public/sw.js`) の push handler が `clients.matchAll()` で判定する W3C 標準パターン。 backend 側は views_ws の在不在だけを見て、 visibility state は持たない。

### `/ws/pty/{sid}`: xterm 入出力経路

`backend/terminal/routes.py::pty_socket` が WebSocket を受け、 PTY (= tmux + claude) の master_fd と client を bridge する。 attach 時に PtySession が存在しない / exit していれば spawn (= `spawn_pty_session(launch_alias=...)`、 ただし既存 tmux 残存時は launch_alias=None で乗っ取り防止)。 切断中の backlog (= claude TUI の定期 redraw / カーソル点滅等) は再接続時に drain して同画面 2-3 回重ね描き事故を防ぐ。

`viewMode='terminal'` を経験した sid だけが LRU (= N=3) で mount され続け、 active 切替で visible / hidden を gate (= xterm 自体は閉じず buffer 経路で出力を吸う)。 chat view 単独運用なら一度も attach しないので、 PTY spawn は `/jsonl/stream/{sid,all}` 経路 + POST /sessions / restart 経路に任せる。

## 接続生存 signal の集約

各経路は `frontend/src/transport/lifecycle.js` の `registerConnection(() => bool)` に「生きてるか」 を judge する callback を登録する。 StatusBar の接続インジケータは全経路の AND を集約表示する (= 1 本切れたら警告)。

各経路は `onopen` / `onmessage` で `notifyConnectionChange()` を呼んで再 evaluate を trigger する。

---

## event wire shape (= `/jsonl/stream/*` で流れる event)

backend `backend/jsonl/events.py::jsonl_line_to_events` が JSONL 1 行から組み立て、 SSE で配信する event 群の wire shape を一括宣言する。 frontend `frontend/src/features/chat/processStreamEvent.js` がこれを type で分岐して描画する。 backend と frontend のどちらか片方だけ変更すると drift して silent な未描画になるため、 新規 event type を追加する時は **本ファイル → backend → frontend** の順で更新する (= 詳細は `architecture/extending.md (b)`)。

### 共通フィールド

全 event は SSE `data:` line に 1 JSON object として乗る。 type 別の payload に加えて、 ほぼ全 event が以下を含む:

| field | 型 | 説明 |
|---|---|---|
| `type` | string | event 種別 (= 下表参照) |
| `uuid` | string? | JSONL 1 行に対応する UUID、 dedup key として使う |
| `parent_tool_use_id` | string? | subagent / Task の親 tool_use_id (= subagent stream を親 turn に紐付ける) |
| `sid` | string? | `/jsonl/stream/all` 経路では必須 (= frontend が振り分けに使う)。 per-sid 経路では省略可 |

### event type 一覧

#### chat / assistant 系

| type | 必須 field | 説明 |
|---|---|---|
| `assistant` | `message.content[]` | assistant 1 turn の content blocks (= text / tool_use / thinking)。 frontend で streaming append |
| `user` | `message.content` | user 行の content (= text or tool_result list)。 `parent_tool_use_id` 持ちは subagent 内 |
| `user_message` | `text` | user 発話を text-only に正規化した shorthand (= UI の bubble 描画用) |
| `result` | `subtype`, `is_error?`, `total_cost_usd?` | claude session の最終 result event (= `subtype: success | error_max_turns | ...`) |
| `ask_user_question` | `question`, `options[]`, `multi`, `tool_use_id` | AskUserQuestion tool 起動時の選択肢、 frontend で AskUserQuestionBubble 描画 |

#### システム / メタ系

| type | 必須 field | 説明 |
|---|---|---|
| `system` | `subtype` | system 行。 subtype = `init` (= session 開始 + cwd / model) / `compact_boundary` (= compact 実行) |
| `system_error` | `error` | api_error / 内部エラー (= ⚠️ 赤カード) |
| `system_note` | `kind`, `text` | scheduled_task_fire / local_command 等の補助通知 |
| `hook_error` | `event`, `error` | hook script 失敗 (= ⚠️ 黄カード) |
| `turn_duration` | `duration_ms` | 1 turn 所要時間 |
| `mode` | `mode` | claude TUI mode 切替 (= 通常 / plan 等) |
| `permission_mode` | `mode` | permission mode 切替 (= acceptEdits / plan / bypassPermissions) |
| `pr_link` | `url` | turn 中に言及された PR URL (= StatusBar 🔗 chip 集約用) |
| `budget` | `remaining_usd` | サブスク残予算 (= StatusBar 描画) |
| `session_end` | (frontend 注入) | restart で claude プロセスを kill した境界 (= MessageList の区切り表示。 backend tail でなく `useChatStream.endSession` が messages に直接挿入) |

#### 添付 / タスク系

| type | 必須 field | 説明 |
|---|---|---|
| `attachment` | `kind`, `payload` | 添付ファイル (= 画像 / pdf 等)。 `kind` で種別、 chat に 1 行折りたたみ表示 |
| `task_notification` | `tool_name`, `task_id`, `status`, `description?` | TaskCreate / TaskUpdate 由来 task 通知。 frontend は task_id で merge して TaskNotification card 描画 |

#### 接続管理

| type | 必須 field | 説明 |
|---|---|---|
| `request_id` | `request_id` | SSE 接続初回に backend が割振る connection ID (= debug 用、 frontend で log)。 jsonl 由来でなく backend route 側で injected |

### 命名規約

- type は **snake_case**、 hyphen / camelCase 禁止
- 同じ概念で複数 event 出る場合 (= `task_notification` の status 違い) は status field で分岐、 type を分けない
- 廃止 type は backend 側 1 round 削除、 frontend は次 round で対応 (= 旧 type を silently 無視する一時 fallback 経路を残さない)

## 変更時の注意

- 新 SSE event type を追加する時は **本 file § event wire shape → backend events.py → backend test snapshot → frontend processStreamEvent → registry/messageRegistry** の順 (= 拡張ガイド = `architecture/extending.md (b)`)
- overview / status の payload shape を変える時は backend + frontend の同時更新が必須 (= 部分受け取り fallback は持たない設計、 silent drift が起きる)
- 新経路を増やす時は **本書の 1 表に 1 行追加** を必ず行う (= drift の根源は表に載らない経路、 で起こる)
