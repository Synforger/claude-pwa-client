# Architecture

> backend / frontend のサブパッケージ構成、 依存方向、 中立基盤 (= `paths.py` /
> `protocol.py` 等)、 1 sid を束ねる `SessionState` + `asyncio.Lock` の意義をまとめる。
> README の「ディレクトリ構成」 は対外向け俯瞰、 本書はその上で **なぜその切り方か** /
> **何を import してよく何を禁忌か** を真値として宣言する。

## 全体像

```
[スマートフォン]                    [ホスト機]
                                  ┌─────────────────────────────────────┐
   PWA (Safari/Chrome) ─────┐     │ FastAPI backend (= 単一プロセス)        │
       │                    │     │   ├ terminal/  (= PTY + tmux 駆動)      │
       │                    ├──▶  │   ├ jsonl/     (= ~/.claude tail)       │
       │                    │     │   ├ routes/    (= HTTP / SSE / WS)      │
   ホーム画面追加 → PWA       │     │   ├ core/     (= push / usage / GC)    │
                            │     │   └ state.py  (= プロセス共有状態 + 集約)│
                            │     │                                          │
                            │     │ moonlight-web-stream                    │ ← 任意 (Path B)
                            │     │   └ Sunshine                            │
                            │     └─────────────────────────────────────────┘
                            │              ↕ Tailscale (= tailnet 内 only)
                            └──────────────┘
```

backend は **シングルプロセス FastAPI** を前提に組まれる。 state は module-level dict +
1 sid あたり 1 `SessionState` の二重 view で持ち、 read-modify-write race を
`asyncio.Lock` で防ぐ (= 後述)。 マルチプロセス / マルチノードへスケールする
設計ではない (= 個人ホスト 1 台 + Tailscale tailnet 内の前提と整合)。

## backend サブパッケージ責務

backend は **4 つのサブパッケージ** + **2 つの中立基盤 module** で構成する。 各
サブパッケージは他サブパッケージを**横方向に import しない**ことを原則とし、
共通利用したい helper は中立基盤に降ろす (= 循環 import / 段数狂い path bug の防止)。

| package | 責務 | 主な file |
|---|---|---|
| `terminal/` | claude TUI を実 PTY + tmux で起動・駆動する入力経路。 control mode (`-CC`) パーサ、 送信確認 + 救済再送 を持つ | `runner.py` / `routes.py` (`/ws/pty` + `/pty/{sid}/send`) / `confirm.py` / `control_mode.py` / `session_resolver.py` |
| `jsonl/` | `~/.claude/projects/<cwd-hash>/<claude_session_id>.jsonl` を tail し、 chat UI 用 event 形式 (= `processStreamEvent` 入力) に変換する出力経路 | `tail.py` (純粋関数) / `events.py` (`jsonl_line_to_events`) / `routes.py` (`/jsonl/stream/{sid}`) / `watcher.py` / `session_status.py` / `notifications.py` / `plan_choices.py` |
| `routes/` | HTTP / SSE / WS の各 endpoint を session / chat / overview / files / hooks / subagents / accounts 単位で分割保持 | `sessions.py` / `chat.py` / `overview.py` (`/sessions/status/stream` + `/sessions/overview/stream` + `/views/ws`) / `files.py` / `hooks.py` / `subagents.py` / `accounts.py` |
| `core/` | 横断ヘルパ。 Web Push、 使用率 (5h / 7d / ctx) 組み立て、 起動時/定期 GC、 会話フォーク (parentUuid lineage 切り出し) | `push.py` / `usage.py` / `maintenance.py` / `fork.py` |

### 中立基盤 (= 全 package から import 可)

| module | 役割 |
|---|---|
| `paths.py` | backend 配下の全 file path (= `DATA_DIR` / `SECRETS_DIR` / `LOGS_DIR` / `SESSION_META_PATH` / `VAPID_PATH` / `SUBSCRIPTIONS_PATH` 等) の single source of truth。 各 module で `Path(__file__).parent[.parent]` を書くとサブパッケージ化や file 移動で段数が狂って "vapid.json が見つからない" 系の事故が再発するため、 path 追加 / 移動は必ずここを起点にする |
| `state.py` | プロセス共有状態 (`sessions_meta` / `stream_states` / `agent_status` / `session_states` / `views_by_conn` / `sessions_overview` broadcaster 等)。 session 操作 helper (`register_session` / `unregister_session` / `rename_session` / `set_notify_mode` / `demote_fork_to_normal`) も同梱 |
| `config.py` | `config.json` の遅延 lookup (= PEP 562 `__getattr__`)。 test 中の `monkeypatch.setattr` で config 切替できるよう **module 上端で AGENTS を bind しない**。 各 module は `import backend.config as _config` → `_config.AGENTS` の都度引きを徹底する |
| `pty_discover.py` | tmux pane 配下の claude プロセス探索 (= terminal が直接使うが、 lsof / ps 経由の OS 依存層を単独 file に隔離) |
| `chat_content.py` | 添付ファイル保存 (uploads/tmp)。 terminal の `/pty/{sid}/send-with-files` が呼ぶ |

## 依存方向 DAG

```
                       ┌────────────────────────────┐
                       │  main.py (= entrypoint)    │
                       │  + lifespan task           │
                       └─────────────┬──────────────┘
                                     │ include_router(...)
        ┌────────────────┬───────────┼─────────────┬──────────────┐
        ▼                ▼           ▼             ▼              ▼
   terminal/        jsonl/        routes/      core/push      core/maintenance
   (PTY 駆動)       (tail/SSE)    (HTTP/SSE/WS) (Web Push)    (GC loop)
        │                │           │             │
        │                │           │             │
        └────────┬───────┴──────┬────┴──────┬──────┘
                 ▼              ▼           ▼
              state.py     chat_content   pty_discover
              (共有状態)    (添付保存)     (プロセス探索)
                 │              │           │
                 └──────────────▼───────────┘
                          paths.py + config.py
                          (中立基盤)
```

**禁忌の依存方向**:

- `state.py` は `usage.py` を import しない (= 逆方向、 `usage → state` のみ。 module init 時の循環 import 回避)
- `terminal/` ↔ `jsonl/` を直接 import しない (= 入出力分離。 共有が必要なら state 経由)
- `routes/*` は他 `routes/*` を import しない (= 横断 helper は state / core に降ろす)
- `paths.py` は何も import しない (= 末端の宣言だけ)

## SessionState + asyncio.Lock の意義

state.py の中核設計判断。 旧設計は `sessions_meta` / `stream_states` / `agent_status` /
`session_tmp_files` / `session_last_seen_at` の **5 dict** を sid キーで並走させ、
`asyncio.Lock` も無く GIL 任せで read-modify-write していた。 `tasks` 配列の lost update、
`pr_links` 重複追加、 overview push 中の上書き race 等の温床になっていた
(= backend-F-07 / F-16 / F-37 / F-38)。

### 解決

1 sid あたり 1 `SessionState` を生成し、 旧 5 dict と**同一 field object を参照する
parallel view** として保持する。 `SessionState` 自身が `asyncio.Lock` を所有する:

```python
@dataclass
class SessionState:
    meta: SessionDef
    stream: StreamState
    status: dict[str, Any]            # = agent_status[sid] の参照を共有
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tmp_files: list[Path] = field(default_factory=list)
    last_seen_at: float | None = None
```

副 path consumer は以下のパターンで atomic 化する:

```python
async with state.get_session(sid).lock:
    status = state.get_session(sid).status
    status["pr_links"].append(...)
```

旧 dict 群を**残したまま**で SessionState を追加するのは、 副 path consumer
(= routes/* / jsonl/* で 30 箇所超) の段階的移行のため。 `register_session` /
`unregister_session` で**両 view を同期**することで、 移行が完了する前でも
壊れない (= round 2 で副 path 直接 dataclass 化を別途扱う)。

### `AgentStatus` dataclass

`agent_status[sid]` の中身は旧来素 dict factory `_make_agent_status` で、 field 名
typo と不揃いの default が広い consumer に潜む構造だった。 `AgentStatus` dataclass に
昇格し factory 1 箇所 / field 名 静的検査 / default 一元 を担保しつつ、 既存
`agent_status[sid][key]` 経由 read/write 互換のため `to_dict()` で plain dict を吐き、
module-level `agent_status` には **dict の方** を入れる (= 副 path 直接 dataclass 化は
別 round)。

### `OverviewBroadcaster`

`/sessions/overview/stream` の fan-out。 旧実装は単一 `asyncio.Event` を全接続で共有し、
1 接続の generator が `clear()` した瞬間に他接続の `wait` が起きそこねて push を落とす
race があった (= iPhone 2 台同時運用で「片方だけ停止ボタンが stuck」 の一因)。 接続
ごとに `Event` を分け、 broadcaster が一括 `notify` する設計に変更済。

## frontend 構成 (= W2 architecture 真の完成、 2026-06-29)

React + Vite。 `main.jsx` → `App.jsx` (= 10 行 shell、 ErrorBoundary + Layout を return するだけ) → `layout/Layout.jsx` (= 55 行本体、 features の side-effect import + 配置のみ) → 各 features が真の責務 owner。 旧 `AppShell.jsx` (= 887 行) は W2 Phase F-4/F-5/F-6 で完全削除済 (ADR-026)、 contract test で再導入 gate 化。

| ディレクトリ | 責務 | 規約 |
|---|---|---|
| `layout/` | 配置層 (= Layout / ChatPanel / TerminalPane / OverlayHost / ErrorBoundary)。 ロジックを持たず、 features 側 component を slot として置くだけ | `Layout.jsx` が features/* の `index.js` を side-effect import で self-register + Topbar / StatusBar / ChatPanel / TerminalPane / OverlayHost / AppEffects を配置。 ChatPanel / TerminalPane は **always-mount + 内部 display:none gate** で viewMode 切替時の state ロスト防止 |
| `features/<name>/` | 機能の真の owner (= 19 機能 = app-effects / ask-user-question / attachments / chat / dialogs / file-preview / file-tree / fork / ios-native / plan-approval / push-notify / screenshare / session-drawer / status-bar / subagents / tasks / terminal / topbar + `__contracts__` test)。 各機能の component / hook / state / handler / 配線 entry が**1 フォルダで自己完結** | `index.js` = 配線 entry、 registry signal + Component lazy spec (= overlay 系のみ、 `Component: () => import('./<X>.jsx')`) を declare。 **lazy 対象 component の static import は禁止** (= chunk 分離を壊す、 contract test で gate 化、 詳細は `extending.md (c)`) |
| `state/` | 6 領域 singleton store (= `ephemeral` / `messages` / `persistence` / `push` / `sessions` / `ui`) + createStore factory (`_store.js`、 ADR-017)。 詳細責務は `state-stores.md` 参照 | 各 feature が `useSyncExternalStore(subscribe, getSnapshot)` で読み + setter 関数直呼出で書き。 hook 二重 instantiate しても state 分裂しない (= J-2 / J-9 / J-11 / J-12 で全 useState 一掃済) |
| `registry/` | 5 registry (= `featureRegistry` / `messageRegistry` / `overlayRegistry` / `pushRegistry` / `streamRegistry`) + 共通 lifecycle 契約 | `register(name, { Component?, dispatch, init?, mount?, unmount? })`、 OverlayHost が `overlayRegistry.list()` を走査して open 中 overlay を lazy + Suspense + LazyBoundary で 1 経路 render |
| `transport/` | backend 接続層 (= `sse-*.js` / `ws-pty.js` / `ws-views.js` / `lifecycle.js` 等)。 SSE / WS の singleton 接続をここに集約 | features → transport は直接 import OK (= ADR-018)、 ports/ interface を transport が implements |
| `domain/` | 純粋 TS layer (= `Session.ts` / `Message.ts` / `Tool.ts` / `Event.ts` + `invariants.ts` 純粋関数) | React 非依存、 worker / test / 別 entry 再利用可能。 型 only file は `types.d.ts` を持たず domain/ 配下に集約 |
| `ports/` | 型 only interface (= `PtyTransport` / `SseTransport` / `EventEmitter`) | hexagonal 境界の契約、 mock 可能性確保 |
| `shared/` | feature 跨ぎの共有 component (= `ConfirmDialog` / `Modal.css` 等) | features 内では完結できない 汎用 UI のみ |
| `hooks/` | generic DOM utility (= `useEscape` / `useOutsideClick` の 2 件のみ) | 機能固有 hook は features 内、 ここには汎用しか入れない |
| `contracts/` | codegen 出力先 (= events / ws_channels / http_endpoints の `.ts` / `.py`、 ADR-015 / 016) | 真値 = `contracts/schema/*.yaml`、 frontend / backend に自動配置 |
| `tools/` | tool block 整形 handler の registry (= `_registry.js` + family file `fileOps.js` / `web.js` / `cron.js` / `task.js` / `todoPlan.js` / `worktree.js` / `agent.js` / `misc.js`) | tool 1 個 = `export const <Name> = { format(input) { ... } }` を family file に書く → `_registry.js` に import + lookup 行 1 つ。 registry 未登録は `utils/format.js::formatTool()` の default fallback で `[displayName] <JSON>` 表示 |

### registry 系の単一情報源

| registry | 役割 |
|---|---|
| `frontend/src/tools/_registry.js` | tool 名 → handler の lookup table。 `utils/format.js::formatTool()` がここを引いて `handler.format(input)` に丸投げ |
| `frontend/src/registry/messageRegistry.js` | `system_*` / `attachment` / `task_notification` 等の system kind ごとの `fromEvent(event)` + `Render` を 1 箇所集約。 旧来は MessageItem.jsx 側の巨大 switch + processStreamEvent 側の重複 append パターンに分散していた (W2 Phase F-1 で registry/ 配下に集約) |
| `frontend/src/features/chat/processStreamEvent.js` | SSE event の `type` 分岐の単一窓口。 messageRegistry / appendSystemMessage / useStreamBuffer に dispatch する (W2 Phase F-1 で `hooks/internal/` から `features/chat/` 配下に移送) |

新 system kind / 新 SSE event type / 新 tool 表示の追加手順は `extending.md` 参照。

## 参考

- 4 SSE + 2 WS 経路 (= status / overview / chat / chat-all / views_ws / pty_ws) の責任分担 + event wire shape = `../protocol/streams.md` (旧 streams + sse-event-shape を統合)
- state stores 6 個の責務 + subscribe 経路 = `state-stores.md`
- 拡張ガイド (= 新 tool / 新 SSE event / 新 modal / 新 account / 新 push channel) = `extending.md`
- `backend/data/*.json` の schema = `reference/data-schemas.md`
