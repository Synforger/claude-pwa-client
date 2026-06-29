# state/ — 6 領域分離 + createStore 共通 helper (= ADR-010, ADR-017)

> **目的**: v1 で 38+ state item が 17 個の hook に散らかってた状態を、 6 領域 (= messages / ephemeral / sessions / ui / persistence / push) に物理分離し、 1 つの場所で「どの state が真値で、 どの state が ephemeral か」 を見渡せる構造にする。

## 構成

```
state/
├── README.md           (本 file)
├── _store.js           createStore factory (= ADR-017、 全 store の subscribe/getSnapshot/setState 共通基盤)
├── messages.js         真値 message store (= uuid 付き user/agent/system、 isPersistableMessage filter)
├── ephemeral.js        streamBuffer / attachments / loading / apiKeySource / sendFailedText / stopUnavailableSid / reconnectKey (J-12 で optimistic / sendTimers / pendingQuestion は retire 済)
├── sessions.js         sessions / activeId / agents / accounts / status / sessionActivity / unreadDone
├── ui.js               overlays / scroll / keyboard / viewModes
├── persistence.js      localStorage 一元化 + debounce + quota retry + auto-flush on lifecycle
└── push.js             Web Push 購読 singleton (= J-2 で usePushSubscription の useState 4 個を統合)
```

> 旧 `transport.js` は W2 Phase J-12 で dead 削除 (= 全 setter が orphan、 isOnline は `transport/lifecycle.js::registerConnection` 経由に集約済)。

## ownership 表

| state | 真値 / ephemeral | 永続化 | owner | 更新経路 |
|---|---|---|---|---|
| messages | 真値 | localStorage (lz-string) | messages.js | features/chat (= SSE handler 経由) |
| sessions | 真値 | localStorage | sessions.js | features/session-drawer (= backend GET / CRUD) |
| status[sid] | 真値 | なし | sessions.js | features/status-bar (= SSE /sessions/status/stream) |
| sessionActivity | 真値 | localStorage | sessions.js | messages 変化に追従 |
| unreadDone | 真値 | localStorage | sessions.js | turn 完了 + 未閲覧で flip |
| activeId | 真値 | localStorage | sessions.js | features/session-drawer / URL deep link |
| agents / accounts | 真値 | なし | sessions.js | 起動時 1 回 GET |
| streamBuffer[sid] | ephemeral | なし | ephemeral.js | SSE handler (rAF coalesce) |
| attachments[sid] | ephemeral | IndexedDB (画像) | ephemeral.js + features/attachments | ChatInput 添付選択 |
| loading[sid] | ephemeral (backend 真値の写し) | なし | ephemeral.js | overview SSE (= 真値) + useChatStream の setLoading wrapper (= per-sid / 全クリア 3 形態) |
| apiKeySource | ephemeral | なし | ephemeral.js | useChatStream init (= J-11) |
| sendFailedText | ephemeral | なし | ephemeral.js | send 失敗時 |
| stopUnavailableSid | ephemeral | なし | ephemeral.js | stop intent 切断検知 |
| reconnectKey | ephemeral | なし | ephemeral.js | EventSource bump 用 counter |
| overlays.* (drawer/menu/favs/...) | UI ephemeral | なし | ui.js | features/* の open/close |
| scroll.* | UI ephemeral | なし | ui.js | features/chat scroll listener |
| keyboard.* | UI ephemeral | なし | ui.js | features/ios-native + features/terminal |
| viewModes[sid] | UI 真値 | localStorage | ui.js | layout/Layout (= chat ↔ terminal toggle) |
| push.hasRealSub / pushBusy / localFlag | ephemeral (backend 真値の写し) | なし | push.js | features/push-notify (= J-2、 AppEffects mount + SessionDrawer remount の両経路で singleton 共有) |

## createStore 使い方 (= ADR-017)

```js
import { createStore } from './_store.js'

// 1) store 作る (= 各 state file の冒頭で 1 回)
const store = createStore({ count: 0 }, { name: 'counter' })

// 2) hooks / features から読む用に subscribe + getSnapshot を export
export const subscribe = (listener) => store.subscribe(listener)
export const getSnapshot = () => store.getSnapshot()

// 3) mutation API を export (= 細粒度の setter)
export function increment() {
  store.setState(prev => ({ ...prev, count: prev.count + 1 }))
}
```

React 側 (= features 層):

```js
import { useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../state/counter.js'

function Counter() {
  const { count } = useSyncExternalStore(subscribe, getSnapshot)
  return <div>{count}</div>
}
```

observability (= W3 で実装する DebugPanel / StateInspector):

```js
import { getAllStoreSnapshots, subscribeAllStores, listStoreNames } from '../state/_store.js'

// 全 store の現在値を 1 経路で読む (= /debug/state にも流す)
const snapshot = getAllStoreSnapshots()

// 全 store の差分 event を 1 listener で受ける (= EventTimeline 用)
const unsub = subscribeAllStores((name, value) => { /* log */ })
```

## 採用 ADR

- **ADR-010** (= Frontend Architecture): state は features / layout から read 、 transport / SSE handler から write。 import direction は boundaries lint で強制。
- **ADR-013** (= PWA Lifecycle): persistence.js が visibilitychange-hidden / pagehide / freeze で必ず flushPending、 BFCache 復帰時の data loss 0。
- **ADR-017** (= createStore 共通化): subscribe / snapshot pattern の 6 重複を撤廃、 observability inspector の入口を 1 経路に。

## 関連

- `../domain/` — Message / Session / Tool / Event 型と純粋関数 (= isPersistableMessage / dedupKey / forkDepth 等)。 state は domain を import して filter / 判定する。
- `../contracts/` — codegen 出力の型。 state は domain 経由で間接的に参照。
- `../transport/` — backend 接続 (= SSE / WS singleton)。 transport が event を受信して state.* の setter を呼ぶ。 store としての `state/transport.js` は J-12 で撤去済 (= 接続生存 signal は `transport/lifecycle.js::registerConnection` に集約)。
- `../features/` — UI 配線。 features は subscribe + getSnapshot で state を読み、 setter で書く。
