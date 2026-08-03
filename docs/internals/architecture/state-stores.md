# State stores (= frontend 7 store の責務 + subscribe 経路)

W2 architecture overhaul (= 2026-06-29 着地) で frontend `state/` は **7 領域 singleton store** に統合された。 各 store は `createStore` factory (= `_store.js`、 ADR-017) 経由で `subscribe` / `getSnapshot` / setter 群を export し、 features は `useSyncExternalStore` 経由で読む / setter 直呼出で書く。 hook 二重 mount しても state 分裂しない構造。

> code 内 真値 = `frontend/src/state/README.md` (= state owner / 永続化 / 更新経路の表)。 本 doc は **「どの feature が どの store を subscribe して、 何の責務を果たすか」** の俯瞰地図 (= state/README.md は store 縦軸、 本 doc は feature 横軸)。

## 7 store 一覧

| store | 責務 | 永続化 | 主な書き手 |
|---|---|---|---|
| `ephemeral.js` | attachments / `loading[sid]` / streamBuffers / sendFailedText / stopUnavailableSid / reconnectKey / attachmentPickerBump の描画専用 ephemeral (= optimistic / sendTimers は J-12、 apiKeySource は 2026-07-27 で退役済) | なし | features/chat (= 送信 / 受信ループ)、 transport/sse-overview (= loading の真値写し) |
| `sessions.js` | sessions list / `activeId` / `agents` / `accounts` / `status[sid]` / `sessionActivity` / `unreadDone[sid]` | localStorage (一部) | features/session-drawer (= CRUD)、 features/status-bar (= status SSE)、 features/topbar (= activeSid 切替) |
| `ui.js` | overlays 11 個 / scroll 4 ref / keyboard 5 modifier / `viewModes[sid]` / desktopOpen / planOpen / storageWarnDismissed | localStorage (= viewModes + unread のみ) | features/* (= 各 overlay open/close)、 features/topbar (= viewMode toggle) |
| `messages.js` | uuid 付き user / agent / system message の真値配列 (= sid 別)、 `MAX_MESSAGES_PER_SID = 200`。 tool_result 内の画像本体は載せない (= `utils/toolResult.js`、 表示は「画像」 1 語に畳むので不変) | localStorage (lz-string 圧縮) | features/chat (= SSE handler 経由)、 useChatStorage |
| `push.js` | Web Push 購読状態 singleton (= hasRealSub / pushBusy / localFlag / pushAvailable 派生)、 W2 Phase J-2 で usePushSubscription の useState 4 個を統合 | なし (= backend 真値、 SW broken listener 経由で同期) | features/push-notify (= AppEffects mount + SessionDrawer remount の両経路から書き、 store singleton で分裂防止) |

| `promptState.js` | terminal prompt 検出 state (= SSE `prompt_state` event の受け皿、 tier / excerpt / controls) | なし | transport 経由の `prompt_state` event、 features/status-bar (= banner + quick-reply が subscribe) |
| `locale.js` | UI 言語 (= 2026-07-02 追加) | localStorage | i18n/t.js + SessionDrawer が subscribe |

旧 `transport.js` store は W2 Phase J-12 で dead 削除済 (= 全 setter が orphan)、 接続生存 signal は `transport/connectionStatus.js::registerConnection` 経由に集約された。

## subscribe 関係性 (= feature × store)

| feature | 主に subscribe する store | 役割 |
|---|---|---|
| `frontend/src/features/chat/` | messages / ephemeral / sessions (activeId) | chat 本文の組み立て + 送信 + 停止、 SSE event を messages に流す |
| `frontend/src/features/chat/useChatStream.js` | sessions (activeId) + 自前 useRef (= optimisticRef) | `/jsonl/stream/{sid}` SSE 接続 + `endSession` (= restart) 経路 |
| `frontend/src/features/session-drawer/` | sessions + ui (overlays.drawer) | タブ一覧 / 切替 / 削除 / fork、 ☰ ボタンで開閉 |
| `frontend/src/features/status-bar/useStatus.js` | sessions (status[sid]) | StatusBar (モデル / 残予算 / 5h/7d/ctx) の描画、 `/sessions/status/stream` SSE 由来 |
| `frontend/src/features/topbar/` | sessions (activeSession) + ui (viewModes[sid] / overlays) | header の各種アイコン (= ⭐ / 📋 / 🤖 / 💬 toggle 等) |
| `frontend/src/features/push-notify/` | push + ui (overlays.notifyMode) | Web Push 購読 / 解除、 通知 mode 切替 |
| `frontend/src/features/app-effects/` | ui + push (= visibility 連動 desktopOpen close、 deep-link、 viewModes 永続化等) | app-wide effect (= 9 種類) を 1 経路で wire |
| `frontend/src/layout/ChatPanel.jsx` | sessions (activeSid) + ui (viewModes) | chat view 主 container、 always-mount で hidden gate |
| `frontend/src/layout/TerminalPane.jsx` | sessions (activeSid) + ui (viewModes) | xterm view、 LRU mount で N=3 sid 維持 |
| `frontend/src/features/terminal/TerminalMount.jsx` | sessions + ui + 自前 LRU singleton (= module-level Set) | viewMode='terminal' 経験 sid を最大 N=3 mount |
| `frontend/src/features/dialogs/` | ui (overlays.confirmEnd / confirmStop) + module-level `endSession` / `stopMessage` impl (= useChatStream の hook 戻り値を unmount で nullify) | ConfirmEndDialog / ConfirmStopDialog の onConfirm 経路 |

## state 分裂防止の設計判断 (= W2 Phase J-2 / J-9 / J-11 / J-12 で sweep)

旧設計は features 内 `useState` を多用しており、 同 hook が複数経路で mount される (= AppEffects + SessionDrawer 等) と state が独立 instance に分裂、 backend 同期は singleton な module-level guard で済んでも UI 観測者の数だけ side-effect が起きる構造だった。 W2 Phase J で以下を sweep:

- **J-2**: `usePushSubscription` の useState 4 個 → `frontend/src/state/push.js` singleton
- **J-9**: `useChatStream` の `loading[sid]` useState → `state/ephemeral.js::loading` setter 直 wire (= SessionDrawer の青/赤丸 badge も同 store を subscribe)
- **J-11**: `useAttachments` + `useChatStream.apiKeySource` → `frontend/src/state/ephemeral.js` 統合
- **J-12**: messages localStorage write の useState mirror → `frontend/src/state/messages.js`、 ui keyboard 7 useState + ui scroll → `frontend/src/state/ui.js`、 useChatStream 3 件 setter dead 削除、 state/transport.js 全削除

検出機構は `.tooling/local-ci/audit-w2-residue.py` (= pre-commit gate)。 新規 state 二重管理 / orphan setter / CSS absolute anchor を 3 軸で検出、 false positive は `audit-w2-residue-allowlist.txt` で suppress。 W2 完成時点で A / B / C 件数 0。

## 拡張時

新 state 領域を足す時:

1. 既存 7 store のどれかに収まらないか自問 (= 「optimistic / SSE 由来 / 永続要否」 で振り分け、 新 store 作るのは最終手段)
2. 新 store が必要なら `createStore({ ... }, { name: '<topic>' })` で 1 file 立てる、 名前は 1 単語 (= ephemeral / sessions / ui 等の粒度感に揃える)
3. `frontend/src/state/README.md` の ownership 表に行追加
4. 本 doc の「7 store 一覧」 + 「subscribe 関係性」 にも 1 行追加 (= drift 源は表に載らない store)
5. `.tooling/local-ci/audit-w2-residue.py` は `state/*.js` を自動走査するので追加登録は不要 (= 置き場所を `state/` 直下にすることが検出の効く条件)
