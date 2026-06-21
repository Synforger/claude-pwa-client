# Streams (= SSE / WebSocket 経路の責任分担)

backend と frontend を繋ぐリアルタイム経路は **3 本の SSE + 1 本の WebSocket** の
合計 4 経路に分かれる。 各経路は単一責任に切ってあり、 経路同士で重複した state を
持たない (= 経路をまたいだ dual-driver で UI が振動する旧来バグの根治構造)。 本書は
4 経路の責任分担を 1 表 + 1 図で宣言する真値とする。

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
   │ (messages)      │          │    processStreamEvent 入力に変換          │
   └─────────────────┘          │                                          │
                                │                                          │
   ┌─────────────────┐  WS      │  /views/ws                  ◀── 視認中    │
   │ useViewsWs      │ ◀───────▶│    sid + Stop 意思を双方向に伝送          │
   │ (sendStopIntent)│          │    (TCP FIN で自動 stale 抹消)            │
   └─────────────────┘          └────────────────────────────────────────┘
```

## 1 表で責任分担

| 経路 | 種別 | backend 実装 | frontend consumer | payload | 接続パターン | 役割 |
|---|---|---|---|---|---|---|
| `/sessions/status/stream` | SSE | `backend/routes/overview.py::all_status_stream` | `frontend/src/hooks/useStatus.js` | `{ <sid>: <AgentStatus dict>, ... }` 全 sid 分の status を 1 dict | mount 1 回張りっぱなし、 activeSid 変化で再接続しない | StatusBar (モデル / mode / 残予算 / 5h / 7d / ctx / 🔗 PR chip)、 pending_question 表示、 pending_plan 表示 |
| `/sessions/overview/stream` | SSE | `backend/routes/overview.py::sessions_overview_stream` | `frontend/src/hooks/useSessionsOverview.js` | `{ <sid>: { busy, pending, last_seen_at, unread_done }, ... }` | mount 1 回張りっぱなし、 全 client / 全タブで共有 | **停止ボタン (= loading[sid]) の唯一のソース**、 ドロワー一覧の青丸 (処理中) / 赤丸 (完了未読)、 未読 last_seen sync |
| `/jsonl/stream/{sid}` | SSE | `backend/jsonl/routes.py::jsonl_stream` | `frontend/src/hooks/useChatStream.js` | `data: {<processStreamEvent event>}\n\n` (= `assistant` / `user` / `result` / `system_*` / `attachment` / `task_notification` 等。 詳細は `docs/sse-event-shape.md`) | activeSid 変化で再接続。 `?from=<offset>` で前回 byte offset 以降の完全行のみ流す (= 初回 replay 軽量化) | 該当 sid の messages 配列 (= chat 本文) を組み立てる |
| `/views/ws` | WebSocket | `backend/routes/overview.py::views_ws` | `frontend/src/hooks/useViewsWs.js` | client → server: `{"sid": "ses_xxx"\|null}` (= 視認中 sid 更新) / `{"type":"stop","sid":"..."}` (= Stop 意思)。 server → client: 受信のみ (broadcast なし) | PWA visible 中だけ常時接続、 3 秒 reconnect。 接続切断 (= TCP FIN / iOS bg 化) で `views_by_conn` から自動削除 | (1) 通知抑制判定 (= `is_session_viewed(sid)` が真なら `broadcast_push` skip) (2) Stop ボタン (= HTTP POST だと race で busy=true 復活する経路を WS の TCP 保証で潰す) |

## 経路別の設計判断 (= なぜこの分け方か)

### `/sessions/status/stream`: 全 sid 1 接続

旧設計は sid 毎に `/status/{sid}/stream` を張り替えていた。 タブ切替のたびに SSE
を旧 close → 新接続し、 iOS Safari の 1-3 秒の TCP 確立コストで「タブ切替したのに
status が出るのが遅い」 体感だった。 全 sid を 1 接続で配信に変更 (= overview と
同パターン) し、 タブ切替で SSE 張り替え不要 → 切替コスト 0。 各 client は受信
payload から自分の activeSid 分を取り出すだけ。

`StreamState.status_event` (per sid `asyncio.Event`) を起点に、 hooks / jsonl 経路で
変化があったら `set()` → SSE 接続側が起きて全 sid snapshot を yield → `clear()`。
接続ごとの diff 配信 (= F-09) で snapshot 不変なら data 行を yield しない。
keep-alive は SSE comment 行のみ (= `:\n\n`、 F-10) で全 sid JSON を毎 20s 流す
無駄を排除。 rate-limits は 1 秒 cache で接続数 × notify 回 read を縮める (= F-56)。

### `/sessions/overview/stream`: backend 権威 busy の唯一のソース

停止ボタン (= `loading[sid]`) の真値は backend が JSONL の `stop_reason` から確定的に
算出した `StreamState.busy` ただ 1 つ。 chat SSE (`useChatStream`) は `loading` を一切
触らない。 旧来は「per-tab assistant/result で loading を上下する」 と「overview で
上書き」 の dual-driver になっており、 イベント取りこぼし / 再接続 / 複数デバイス
で振動していた (= 2026-06-03 根本治療)。

overview は毎回フル snapshot なので、 取りこぼし / 再接続 / 複数デバイスでも次の
snapshot で必ず正しい状態に収束する (= reconcile-on-snapshot)。 楽観意図
(`optimisticRef`) は送信 / 停止 直後の逆向き古 snapshot から UI を保護する短期
ウィンドウのみで、 1500ms タイマー駆動は撤去し snapshot 駆動の event ベースに揃えた。

fan-out は `OverviewBroadcaster` (= per-connection `asyncio.Event` を broadcaster が
一括 `notify`)。 旧実装の単一 `Event` 共有では 1 接続の generator が `clear()` した
瞬間に他接続の `wait` が起きそこねて push を落としていた。

### `/jsonl/stream/{sid}`: 入出力分離の「出力」 側

claude を PTY/TUI 経路で動かすと、 全 turn が
`~/.claude/projects/<cwd-hash>/<claude_session_id>.jsonl` に追記される。 これを
backend が tail し `jsonl_line_to_events` で `processStreamEvent` 入力形式に変換 →
SSE で配信することで、 proxy / SDK / `-p` を一切使わず chat UI を再構成できる
(= subscription 枠で動く、 軽い)。

入力 (= キー送信) は `terminal/routes.py` の `/ws/pty` + `/pty/{sid}/send` 系。
**出力 = JSONL tail / 入力 = キー送出** を strict に分離することで、 claude CLI が
書く真値だけが UI に出る (= backend 中央で偽 event を合成しない)。

### `/views/ws`: 視認シグナル = 接続生存

「今どの sid を見ているか」 を realtime に backend へ伝える。 接続中の間 sid を
保持し、 `broadcast_push` の `is_session_viewed(sid)` 判定に使う。 TCP FIN /
iOS bg 化での socket 切断 = 視認終了として自動削除されるので、 **stale 概念が
構造的に存在しない** (= 過去に visibility state を backend が持ったときの「通知が
永久抑制される」 バグの再発防止)。

Stop ボタン経路も WS で通す。 HTTP POST 経路だと送信失敗 race で overview SSE が
busy=true を流し停止ボタンが復活していた。 WS 接続中なら TCP 保証で届く、 切断中
(= PWA が見えてない) なら stop は押せないので何もしない、 で正当性を担保する。

可視タブでの通知抑制は **SW** (`frontend/public/sw.js`) の push handler が
`clients.matchAll()` で判定する W3C 標準パターン。 backend 側は views_ws の在不在
だけを見て、 visibility state は持たない。

## 接続生存 signal の集約

4 経路はそれぞれ `frontend/src/hooks/useConnectionStatus.js` の
`registerConnection(() => bool)` に「生きてるか」 を judge する callback を登録する。
StatusBar の接続インジケータは全経路の AND を集約表示する (= 1 本切れたら警告)。

各経路は `onopen` / `onmessage` で `notifyConnectionChange()` を呼んで再 evaluate を
trigger する。

## 変更時の注意

- 新 SSE event type を `/jsonl/stream/{sid}` に足す時は `docs/sse-event-shape.md` →
  `backend/jsonl/events.py::jsonl_line_to_events` → `frontend/src/hooks/internal/processStreamEvent.js`
  の順 (= 拡張ガイド = `docs/extending.md`)
- overview / status の payload shape を変える時は backend + frontend の同時更新が必須
  (= 部分受け取り fallback は持たない設計、 silent drift が起きる)
- 新経路を増やす時は **本書の 1 表に 1 行追加** を必ず行う (= drift の根源は表に載らない
  経路、 で起こる)
