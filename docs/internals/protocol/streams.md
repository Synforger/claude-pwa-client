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
| `/ws/pty/{sid}` | WebSocket | `backend/terminal/routes.py::pty_socket` | `frontend/src/features/terminal/Terminal.jsx` (= xterm.js、 WS 直書き) | client → server: `{"type":"input","data":"..."}` (= tmux send-keys 転送) / `{"type":"resize", ...}`。 server → client: `{"type":"output","data":"..."}` (= PTY 出力 bytes) | viewMode='terminal' 切替時に attach、 切断中は backend が `session.output_queue` に backlog 蓄積 (drain on reconnect) | xterm.js の入出力経路。 chat view のみ使う場合は接続しない (= W2 後は POST /sessions / restart 経路で backend 側 PTY spawn が完結するので、 chat view 単独で claude 起動が走り切る) |

## 経路別の設計判断 (= なぜこの分け方か)

### status channel: 全 sid 1 接続 (= 旧 /sessions/status/stream、 2026-07-27 に unified へ一本化)

旧設計は sid 毎に `/status/{sid}/stream` を張り替えていた。 タブ切替のたびに SSE を旧 close → 新接続し、 iOS Safari の 1-3 秒の TCP 確立コストで「タブ切替したのに status が出るのが遅い」 体感だった。 全 sid を 1 接続で配信に変更 (= overview と同パターン) し、 タブ切替で SSE 張り替え不要 → 切替コスト 0。 各 client は受信 payload から自分の activeSid 分を取り出すだけ。

`StreamState.status_event` (per sid `asyncio.Event`) を起点に、 hooks / jsonl 経路で変化があったら `set()` → SSE 接続側が起きて全 sid snapshot を yield → `clear()`。 接続ごとの diff 配信 (= F-09) で snapshot 不変なら data 行を yield しない。 keep-alive は data 行 heartbeat `{"ch":"sys","_hb":1}` を 20s 間隔で流す (= client の生存監視 watchdog が受信時刻を読める形。 全 sid JSON を毎 20s 流す無駄は F-10 と同じく排除)。 rate-limits は 1 秒 cache で接続数 × notify 回 read を縮める (= F-56)。

### overview channel: backend 権威 busy の唯一のソース (= 旧 /sessions/overview/stream)

停止ボタン (= `loading[sid]`、 真値は `frontend/src/state/ephemeral.js`) は backend 権威の busy ただ 1 つ。 busy の原義は「claude が考えている時」 で、 (a) JSONL の `stop_reason` から確定算出する `StreamState.busy` と (b) 画面の実況 (= prompt_detector_loop が観測する TUI 推論中スピナー `Thinking… (Ns`、 `StreamState.pane_working`) の **OR** (= 2026-07-10。 queue 消化中の無言時間など JSONL 簿記が拾えない区間もスピナーが回っていれば推論中を維持、 `user_stopped` は両者に優先して false)。 chat SSE (`useChatStream`) も `loading` を一切触らない (= 旧 useState 経路は J-9 で `frontend/src/state/ephemeral.js` singleton に統合済)。 旧来は「per-tab assistant/result で loading を上下する」 と「overview で上書き」 の dual-driver になっており、 イベント取りこぼし / 再接続 / 複数デバイスで振動していた (= 2026-06-03 根本治療)。

overview は毎回フル snapshot なので、 取りこぼし / 再接続 / 複数デバイスでも次の snapshot で必ず正しい状態に収束する (= reconcile-on-snapshot)。 楽観意図 (`optimisticRef`) は送信 / 停止 直後の逆向き古 snapshot から UI を保護する短期ウィンドウのみで、 1500ms タイマー駆動は撤去し snapshot 駆動の event ベースに揃えた。

fan-out は `OverviewBroadcaster` (= per-connection `asyncio.Event` を broadcaster が一括 `notify`)。 旧実装の単一 `Event` 共有では 1 接続の generator が `clear()` した瞬間に他接続の `wait` が起きそこねて push を落としていた。

### jsonl channel: 入出力分離の「出力」 側 (= 旧 /jsonl/stream/*)

claude を PTY/TUI 経路で動かすと、 全 turn が `~/.claude/projects/<cwd-hash>/<claude_session_id>.jsonl` に追記される。 これを backend が tail し `jsonl_line_to_events` で `processStreamEvent` 入力形式に変換 → SSE で配信することで、 proxy / SDK / `-p` を一切使わず chat UI を再構成できる (= subscription 枠で動く、 軽い)。

全 sid を unified の 1 接続で受け (= 旧 per-sid 張り替え方式は退役)、 全タブの差分を localStorage の offset map で位置を track する。 接続時に sessions_meta の全 sid に `ensure_pty_session_for` を sweep するので、 接続中に既に存在する sid は chat view を開いただけで claude が立ち上がる。 ただし接続継続中に POST /sessions で新規追加された sid は sweep 漏れるので、 `create_session` 側でも `ensure_pty_session_for` を呼ぶ (= 2026-06-29 race 修正)。

入力 (= キー送信) は `/ws/pty/{sid}` + `/pty/{sid}/send` 系。 **出力 = JSONL tail / 入力 = キー送出** を strict に分離することで、 claude CLI が書く真値だけが UI に出る (= backend 中央で偽 event を合成しない)。

### view 申告 (= control op=view / op=stop、 旧 /views/ws)

「今どの sid を見ているか」 を unified 接続の control (op=view) で backend へ伝える。 接続中の間 sid を保持し、 `broadcast_push` の `is_session_viewed(sid)` 判定に使う。 接続切断 = 視認終了として自動削除されるので、 **stale 概念が構造的に存在しない** (= 過去に visibility state を backend が持ったときの「通知が永久抑制される」 バグの再発防止)。

Stop ボタン経路も同 control (op=stop) で通す。 素の HTTP POST 経路だと送信失敗 race で overview SSE が busy=true を流し停止ボタンが復活していた経緯があり、 権威記録として backend が user_stopped を立てる。

可視タブでの通知抑制は **SW** (`frontend/public/sw.js`) の push handler が `clients.matchAll()` で判定する W3C 標準パターン。 backend 側は view 申告の在不在だけを見て、 visibility state は持たない。

### `/ws/pty/{sid}`: xterm 入出力経路

`backend/terminal/routes.py::pty_socket` が WebSocket を受け、 PTY (= tmux + claude) の master_fd と client を bridge する。 attach 時に PtySession が存在しない / exit していれば spawn (= `spawn_pty_session(launch_alias=...)`、 ただし既存 tmux 残存時は launch_alias=None で乗っ取り防止)。 切断中の backlog (= claude TUI の定期 redraw / カーソル点滅等) は再接続時に drain して同画面 2-3 回重ね描き事故を防ぐ。

`viewMode='terminal'` を経験した sid だけが LRU (= N=3) で mount され続け、 active 切替で visible / hidden を gate。 hidden な terminal は **WS ごと切断**し、 visible 復帰時に再接続 + `terminal.reset()` + Ctrl-L で TUI に最新画面を描き直させる (= 旧方式の「描画だけ skip して受信継続」 は見てない端末の全 PTY バイトを client が無線受信し続け、 携帯発熱の主犯級だった)。 chat view 単独運用なら一度も attach しないので、 PTY spawn は `/jsonl/stream/{sid,all}` 経路 + POST /sessions / restart 経路に任せる。

tmux server は `exit-empty off` + 番兵 session `claudepwa-sentinel` (= backend 起動時と各 spawn 前に `ensure_tmux_resilience` が冪等適用) で「最後の session の kill = server 死 = 全 claude 消失 → 次の attach で `claude --resume` 一斉再走」 のカスケードを封じている。 番兵は `pwa-` prefix を持たないため maintenance の残骸掃除の対象外。

## `/stream/unified`: 多重化 1 本接続 (= 2026-07-14 電力効率工事)

旧構成のクライアント 1 台あたり SSE/WS 4-5 本 (= jsonl all + status + overview + per-sid subagents + views ws) を、 1 本の SSE + 制御 POST に畳んだ経路。 `backend/routes/unified_stream.py` 実装、 endpoint 契約は `contracts/schema/http-endpoints.yaml` の `/stream/unified` 2 entry が真値。

- **channel envelope**: data 行 JSON `{"ch": "sys"|"jsonl"|"status"|"overview"|"subagents", ...}`。 jsonl frame は `{ch, pos, ev}` で `ev` は既存 sse-events event そのまま (= wire 内容の schema 変更なし)、 `pos` が行末実 byte 位置 (= client は frame ごとに offset 前進、 SSE id 行は使わない)
- **購読 sid だけ配る**: jsonl channel は接続 query (= jsonl=sid:off,...) / control の op=jsonl で宣言された sid のみ。 未購読 sid の event (= 巨大 tool_result 含む) はネットワークにも client CPU にも届かない (= 全配信 fan-out の遮断、 電力主犯対策)。 タブ切替 = 再接続でなく購読差替 + 差分 replay
- **warmup も購読 sid のみ**: 旧 `/jsonl/stream/all` の「接続時に全 sid PTY sweep」 を廃止。 未購読 sid は購読された瞬間に ensure
- **views/ws の吸収**: op=view で視認申告、 SSE 切断 = views 登録自動消滅 (= WS の TCP FIN と同じ stale-free 性質)。 Stop は op=stop (= POST は TCP 保証で届く、 旧 WS 経路と等価)
- **status / overview**: 接続毎 diff 配信 (= F-09 と同規約) を 1 pump に統合。 subagents は op=subagents で対象 1 sid を watch
- **keep-alive**: `{"ch":"sys","_hb":1}` を 25s 間隔 (= 全 channel 共通の 1 心拍、 旧 4-5 本分の heartbeat が 1 本に)

旧 endpoint 群 (= per-sid SSE / stream/all / status/stream / overview/stream / views/ws) は 2026-07-27 に**退役** (= 実利用が旧 bundle の居座りタブのみと確認、 route ごと削除。 旧 bundle のタブは live 更新が止まるが開き直しで新 bundle が入る)。

**frontend は既定で本経路を使う**: `frontend/src/transport/unified.ts` (= singleton 本体) + `select.ts` (= 実装選択の 1 点、 consumer は select 経由で受け取る)。 旧 legacy transport と cpc_transport flag は 2026-07-27 に退役 (= unified が唯一の経路)。 offset は cpc_v2_jsonl_offsets、 status hydrate cache は cpc_last_all_status (= transport/statusCache.ts)。

## `GET /jsonl/history/{sid}`: 状態は GET、 stream は差分 (= client=射影)

タブ表示時に **履歴の権威スナップショット**を 1 発で取る経路 (= `backend/jsonl/routes.py::get_chat_history`)。 stream の初回 replay に履歴復元を依存させないための「状態は GET / stream は差分だけ」 分離で、 stream が復帰し損ねても履歴は必ず取れる。

- **返すもの**: `{events, pos}`。 `events` は SSE と同形状 (= 同じ ingest pipeline を通す、 uuid dedup で cache とも stream replay とも重複しない)、 `pos` は読み終えた byte 位置
- **窓**: `from` 指定ありはその位置以降、 未指定 / 無効は直近 N 行 (= `INITIAL_REPLAY_LINES`)。 frontend は **`from` を付けない**: offset は streaming 中の in-flight を含まず先行し得るため、 offset 起点にすると作業中のツール履歴が飛ばされる
- **転送量の削減** (= 2026-07-27、 携帯 + Tailscale 経由の体感速度): 実測 1.18MB → 247KB
  - **JSON gzip** (= `backend/core/compression.py`)。 **SSE は対象外** — content-type が `text/event-stream` のものは素通しする。 streaming を圧縮すると gzip の内部 buffer に event が滞留してライブ更新が詰まるため、 ここは構造的に分けている (= pin: `backend/tests/test_compression.py::test_sse_is_never_compressed`)
  - **表示に使われない本文の除去** (= `_shrink_tool_results`)。 履歴の 65% が tool_result で、 その大半が base64 画像だった。 UI は tool_result 内の画像を「画像」 プレースホルダ 1 語に畳む (= `utils/format.js`) ので本体は 1 byte も表示に使われない → 履歴経路に限り画像本体を落とし、 長大 text も冒頭 `TOOL_RESULT_PREVIEW_CHARS` に切り詰める。 元の文字数は `full_chars` で残し、 UI の文字数ラベルはそれを使うので表示は不変 (= pin: `backend/tests/test_jsonl_routes.py::test_shrink_tool_results_drops_image_payload_but_keeps_placeholder`)
  - **ライブ SSE は無改変**: 進行中の tool 出力は従来通り完全な形で届く (= 切り詰めは「画面外の過去ログを読み直す時」 だけの最適化。 pin: `backend/tests/test_jsonl_routes.py::test_shrink_tool_results_never_touches_assistant_or_user_message`)
  - **画像本体を落とすのは受け取った側の責務** (= `frontend/src/utils/toolResult.js`)。 無改変で届いた tool_result をそのまま state に載せると、 履歴経由の同じ会話は軽いのにライブ経由だけ重い、 という非対称が client 側に残る (= 2026-08-03 実測: 200 件の保存窓に 2.58MB、 うち 2.56MB が表示に使われない画像。 保存前の structured clone だけで main thread が 150-500ms 停止)。 state に入れる時と保存形への射影で同じ縮小を掛けて対称にする。 UI の畳み方 (= 「画像」 1 語) は変わらないので表示は不変

## 接続生存 signal の集約

各経路は `frontend/src/transport/lifecycle.ts` の `registerConnection(() => bool)` に「生きてるか」 を judge する callback を登録する。 StatusBar の接続インジケータは全経路の AND を集約表示する (= 1 本切れたら警告)。

各経路は `onopen` / `onmessage` で `notifyConnectionChange()` を呼んで再 evaluate を trigger する。

---

## event wire shape (= `/jsonl/stream/*` で流れる event)

backend `backend/jsonl/events.py::jsonl_line_to_events` が JSONL 1 行から組み立て、 SSE で配信する event 群の wire shape を一括宣言する。 frontend `frontend/src/features/chat/processStreamEvent.js` がこれを type で分岐して描画する。 backend と frontend のどちらか片方だけ変更すると drift して silent な未描画になるため、 新規 event type を追加する時は **本ファイル → backend → frontend** の順で更新する (= 詳細は `../architecture/extending.md (b)`)。

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
| `system` | `subtype` | system 行。 subtype = `compact_boundary` (= compact 実行) |
| `system_error` | `error` | api_error / 内部エラー (= ⚠️ 赤カード) |
| `system_note` | `kind`, `text` | scheduled_task_fire / local_command 等の補助通知 |
| `hook_error` | `event`, `error` | hook script 失敗 (= ⚠️ 黄カード) |
| `turn_duration` | `duration_ms` | 1 turn 所要時間 |
| `mode` | `mode` | claude TUI mode 切替 (= 通常 / plan 等) |
| `permission_mode` | `mode` | permission mode 切替 (= acceptEdits / plan / bypassPermissions) |
| `pr_link` | `url` | turn 中に言及された PR URL (= StatusBar 🔗 chip 集約用) |
| `budget` | `remaining` | サブスク残予算 (= StatusBar 描画) |
| `prompt_state` | `state`, `input_mode`, `options[]` | tmux pane の入力待ち検出 (= prompt detector)。 JSONL 由来でなく `backend/terminal/prompt_detector_loop.py` が状態遷移 / excerpt 変化時のみ publish。 ChatPanel の banner + quick-reply button が消費、 返信は `POST /pty/{sid}/send-raw-key`。 field 詳細 = `contracts/schema/sse-events.yaml` |
| `session_end` | (frontend 注入) | restart で claude プロセスを kill した境界 (= MessageList の区切り表示。 backend tail でなく `useChatStream.endSession` が messages に直接挿入) |

#### 添付 / タスク系

| type | 必須 field | 説明 |
|---|---|---|
| `attachment` | `kind`, `payload` | 添付ファイル (= 画像 / pdf 等)。 `kind` で種別、 chat に 1 行折りたたみ表示 |
| `task_notification` | `tool_name`, `task_id`, `status`, `description?` | TaskCreate / TaskUpdate 由来 task 通知。 frontend は task_id で merge して TaskNotification card 描画 |

#### 接続管理

| type | 必須 field | 説明 |
|---|---|---|

### 命名規約

- type は **snake_case**、 hyphen / camelCase 禁止
- 同じ概念で複数 event 出る場合 (= `task_notification` の status 違い) は status field で分岐、 type を分けない
- 廃止 type は backend 側 1 round 削除、 frontend は次 round で対応 (= 旧 type を silently 無視する一時 fallback 経路を残さない)

## 変更時の注意

- 新 SSE event type を追加する時は **本 file § event wire shape → backend events.py → backend test snapshot → frontend processStreamEvent → registry/messageRegistry** の順 (= 拡張ガイド = `../architecture/extending.md (b)`)
- overview / status の payload shape を変える時は backend + frontend の同時更新が必須 (= 部分受け取り fallback は持たない設計、 silent drift が起きる)
- 新経路を増やす時は **本書の 1 表に 1 行追加** を必ず行う (= drift の根源は表に載らない経路、 で起こる)
