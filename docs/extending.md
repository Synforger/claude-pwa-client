# Extending (= 拡張点ガイド)

新 tool / 新 SSE event / 新 modal / 新 account / 新 push channel を足す時の手順を
1 箇所に集約する。 各手順は **「触る file の順序」** を厳守すること (= 順序を崩すと
backend / frontend drift で silent な未描画 / 未配信が出る)。

責任分担の前提は `docs/architecture.md` / `docs/streams.md` / `docs/sse-event-shape.md` を
読んでいることを想定する。

---

## (a) 新 tool の表示を足す

claude が `tool_use` で呼ぶ任意の tool block を chat UI で見栄え良く出すための整形を
追加する。 表示が要らない (= 既存 default fallback で `[displayName] <JSON>` 形式で
出れば十分) なら何もしなくてよい。

### 手順

1. 既存 family file (= `frontend/src/tools/fileOps.js` / `web.js` / `cron.js` /
   `task.js` / `todoPlan.js` / `worktree.js` / `agent.js` / `misc.js`) のうち、
   意味的に近い family に `export const <ToolName> = { format(input) { ... } }`
   を追加する。 family がなければ `misc.js` に置くか、 新 family file を作る
2. `frontend/src/tools/_registry.js` に `import` 行 + `toolHandlers` 表に 1 行追加
3. summary 表示の文字長は `_shared.js` の `SHORT_LABEL_MAX` (= 60) + `truncate()` で揃える
4. backend 側の対応は不要 (= tool block は `assistant` event の `content[]` に乗って
   そのまま流れる)

### 表示要件が複雑な場合 (= 専用 bubble)

`AskUserQuestion` / `ExitPlanMode` のような特殊 UI は **tool registry でなく** event
レベルで分岐する (= `ask_user_question` / `pending_plan` 等の専用 event が
`processStreamEvent` で扱われる)。 その場合は (b) の手順に従う。

---

## (b) 新 SSE event 種別を足す

`/jsonl/stream/{sid}` SSE に新しい event `type` を流して chat に新カードを出す。
**真値は `docs/sse-event-shape.md`** で、 backend / frontend の実装はその下流。

### 手順 (順序厳守)

1. **`docs/sse-event-shape.md` に新 `type` 行を追加** (= 仕様確定、 必須 field 明示)。
   命名は snake_case、 同概念で複数 event 出るときは status field で分岐 (= type 分割しない)
2. **`backend/jsonl/events.py::jsonl_line_to_events`** (or `_system_events` / `_assistant_events` /
   `_user_events` / `_attachment_events` / `_queue_operation_events` の該当 sub) で
   emit を追加 / 修正する
3. **`backend/tests/integration/test_sse_event_snapshot.py`** に snapshot を追加 (= drift
   検知の構造的 gate)
4. **`frontend/src/hooks/internal/processStreamEvent.js`** に新 `type` の分岐を追加。
   system 系 (= `system_*` / `attachment` / `task_notification`) なら
5. **`frontend/src/messageRegistry.js`** に `kind → { fromEvent, Render }` ペアを 1 つ
   追加する。 `appendSystemMessage(setMessages, sid, kind, fromEvent(event))` の 1 行で
   配線完結。 chat / assistant 系 (= 専用 bubble) なら component を `components/`
   配下に置いて processStreamEvent から直接 dispatch
6. **`frontend/src/types.d.ts`** の shape 宣言を更新

### 順序を崩した時の典型バグ

- backend だけ追加 → frontend で silent に無視されて画面に出ない
- frontend だけ追加 → backend が emit しないので分岐が永久に走らない
- shape doc だけ更新 → 実装側で drift 検知できない

廃止 type は backend 1 round で削除 → frontend は次 round で対応 (= 旧 type を silently
無視する一時 fallback は残さない、 残ると後で清掃できなくなる)。

---

## (c) 新 modal / 全画面 overlay を足す

中央モーダル / サイドドロワー / 全画面プレビュー / popover ピッカーを追加する。
v2 architecture では overlay は `frontend/src/features/<name>/` 配下に置く (= ADR-010
self-register、 旧 `frontend/src/overlays/` は廃止)。

### 手順

1. **`frontend/src/features/<name>/<Name>.jsx`** を新規作成 (= 命名 `<Name>.jsx` +
   `<Name>.css` 同居)。 共通枠の CSS は `frontend/src/shared/Modal.css` を import する
2. **`frontend/src/features/<name>/index.js`** で `registerOverlay('<key>', { dispatch: ... })`
   を呼ぶ (= ADR-010 self-register の registry signal)。 **配線 entry から component を
   static import しない** (= 下記「(c) 注意点」 参照)
3. **`frontend/src/layout/AppShell.jsx`** に
   `const <Name> = lazy(() => import('../features/<name>/<Name>.jsx'))` を 1 行追加 +
   `<LazyBoundary><Suspense fallback={null}><<Name> .../></Suspense></LazyBoundary>` で
   render を追加。 初回 paint には乗らず、 開いた瞬間だけ chunk を fetch する設計を
   維持すること (= 初回 bundle 削減、 ADR-025)
4. ESC 閉じは `frontend/src/hooks/useEscape.js`、 outside-click は
   `frontend/src/hooks/useOutsideClick.js` を使う (= 全 overlay が同じ仕組みに揃う)
5. 開閉 state は `frontend/src/hooks/useOverlays.js` に集約する (= 複数 overlay の
   排他制御 / 重ね順を 1 箇所で持つ)。 将来 `state/ui.js` への統合は `plans/w2-completion.md`
   Phase B で予定

### (c) 注意点 = 配線 entry の static import 禁止 (= ADR-025、 contract test 強制)

`features/<name>/index.js` (= 配線 entry) で `import './<Name>.jsx'` のように lazy 対象
component を **static import するのは禁止**。 vite が AppShell.jsx 側の dynamic import を
相殺して `INEFFECTIVE_DYNAMIC_IMPORT` 警告を出し、 chunk 分離が壊れて main bundle に
混入する (= ADR-025 § 背景の bundle 33kB+ 膨らみ事案)。

配線 entry に書いて良いもの:
- `register(<key>, { dispatch })` 系の registry signal
- pure module / helper の touch import (= `favorites.js` 等、 lazy 対象でない state / data 層)
- hook の touch import (= `useSessions.js` 等、 lazy 対象でない、 ただし AppShell.jsx から
  直接 import される hook はここでの重複 import 不要)

書いてはいけないもの:
- AppShell.jsx で `lazy(() => import('../features/<x>/<Name>.jsx'))` されている component の
  static import (= chunk 分離が壊れる)

contract test (= `frontend/src/features/__contracts__/no-lazy-component-static-import.test.js`)
が AppShell.jsx の lazy 対象を grep で動的列挙、 各 features/<x>/index.js の static import が
lazy 対象と交差しないことを vitest で gate 化している。 配線 entry を編集したら必ず
`npx vitest run src/features/__contracts__/` 緑を確認。

### overlay として `features/` に置かないもの

- 常時 mount される本文の構成要素 (= ChatInput / StatusBar / ActivityBar / MessageItem 等)
  → `features/<name>/` 配下に置くが、 AppShell.jsx から直接 import + 常時 render
  (= lazy 対象外)
- 表示位置固定だが「覆いかぶさらない」 UI → 同上
- 純データ helper / hook → `utils/` / `hooks/` / `state/`

---

## (d) 新 Claude account を足す (= 個人 / 会社 OAuth プロファイル切替)

タブを起動する時に `CLAUDE_CONFIG_DIR` 等の env を差し替えて、 別の Claude OAuth
プロファイルで `claude` CLI を立ち上げる。

### 手順

1. **`backend/config.json`** の `accounts` セクションに key を追加:
   ```json
   {
     "accounts": {
       "personal": { "display_name": "個人", "env": {} },
       "work":     { "display_name": "会社", "env": { "CLAUDE_CONFIG_DIR": "REDACTED_PATH" } },
       "<new_id>": { "display_name": "<表示名>", "env": { "CLAUDE_CONFIG_DIR": "<別 ~/.claude>" } }
     }
   }
   ```
2. backend 再起動 (= `config.py` は遅延 lookup なので再起動後の次タブから反映)
3. frontend では新タブ作成 UI (= `frontend/src/hooks/useSessions.js` 経由) が
   `/accounts` endpoint (`backend/routes/accounts.py`) から自動で選択肢を引く
4. **コード変更不要** (= `state.SessionDef.account_id` が任意の string を受ける設計、
   spawn 時に `accounts[account_id].env` を tmux env として注入する)

### 注意

- `~/.claude-work` 等の別 dir は事前に **手動で `claude` を一度立ち上げて OAuth
  認証を済ませておく**。 backend は env 差し替えのみで、 認証フローは持たない
- account 削除時に既存タブが当該 account_id を参照していると、 起動時 warn を出して
  skip される (= session_meta.json から消えはしないので、 必要なら手動掃除)

---

## (e) 新 Web Push チャネル / 通知種別を足す

`AskUserQuestion` / `Stop` 以外の新しい起点で通知を出したい場合の経路。 既存 push
基盤 (`backend/core/push.py` + `frontend/public/sw.js`) を拡張する。

### 手順

1. **`backend/jsonl/notifications.py`** (= 停止要因の検出 / Web Push 発火を担当) に
   新しい trigger 判定を追加。 既存の `maybe_push_blockers` パターンに揃える
2. **`backend/core/push.py::broadcast_push`** を呼ぶ (= subscriber 一括配信 + 未読
   カウンタ更新 + SSE listener 通知)。 必要なら新しい `kind` field を payload に追加
3. **`frontend/public/sw.js`** の `push` event handler に新 `kind` の分岐を追加。
   visible タブ抑制は `clients.matchAll()` で判定する W3C 標準パターンを踏襲
   (= backend 側で抑制しない、 過去に「永久抑制」 バグの原因になった)
4. 通知音 / バナーの可否は session の `notify_mode` (= both / banner / off) を
   尊重する (= `state.set_notify_mode` 経由で永続化される 3 値、 push payload に
   含めて sw.js が判定)

### iOS の制約

- iOS 16.4+ かつ **ホーム画面追加済み**でないと Web Push を受信できない
- 「音のみ (バナー無し)」 は Web Push の仕様上作れない (= `notify_mode = banner` は
  消音バナー、 `both` が音 + バナー)

---

## 拡張時の共通注意

- **shape 真値 → 実装** の順を崩さない (= b の手順を参照)
- backend / frontend / docs の 3 点更新を 1 PR で完結させる (= 中間 commit で
  片側だけ着地すると runtime drift が出る)
- 新規 helper を生やす前に **`backend/state.py` / `frontend/src/utils/` / `hooks/`
  に既存物がないか確認** (= `_registry` / `messageRegistry` / `applyOverviewSnapshot`
  等、 拡張点は既に分離済の場合が多い)
- 中立基盤 (= `backend/paths.py` / `backend/config.py`) に新 path / 新 config を
  追加する時は 1 箇所宣言を貫く (= 各 module で `Path(__file__).parent[.parent]` を
  書かない)
