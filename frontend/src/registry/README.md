# registry/ — 5 ディスパッチ層 + 共通 helper (= ADR-010, ADR-017 対称)

> **目的**: features/<name>/ が「自分の存在を register する」 1 行で配線が完了する構造を作る。 App.jsx に個別の if / wiring を書かない (= 設計書 § 2-5 アドオン拡張点暗黙の構造的根本対策)。 5 種類の registry が同じ lifecycle 契約 (= init / mount / unmount / dispatch) を共有し、 すべて `_registry.js` の createRegistry で生成。

## 構成

```
registry/
├── README.md           (本 file)
├── _registry.js        createRegistry factory + observability snapshot 入口 (= ADR-017 と対称な共通化、 5 重複撤廃)
├── streamRegistry.js   SSE event type → handler (= ADR-011 unknown は graceful handle)
├── messageRegistry.js  message kind → fromEvent + Render component (= v1 流儀継承)
├── overlayRegistry.js  overlay name → open/close + state/ui との同期
├── pushRegistry.js     push channel → handler (= service worker / backend からの分配)
└── featureRegistry.js  feature name → enable/disable + 依存解決 (= isEnabled(name) で実効判定)
```

## RegistryHandler 契約 (= ADR-010 lifecycle 契約型)

```ts
interface RegistryHandler {
  init?: () => void | Promise<void>   // register 直後に 1 回実行
  mount?: () => void                  // App.jsx mount 後 dispatch 開始前
  unmount?: () => void                // hot reload / feature disable / unregister
  dispatch: (arg: unknown) => unknown // 必須
  // featureRegistry のみ:
  requires?: string[]                 // 依存する他 feature 名
}
```

## loud fail policy (= 設計書 § 2-4 silent skip 蓄積の根本対策)

- **同 key 重複 register** → throw (= `{replace: true}` でホットリロード上書き許可)
- **未定義 key dispatch** (= onMissing): `warn` / `throw` / `silent` を registry ごとに選ぶ
  - stream: `warn` (= ADR-011 unknown event graceful)
  - overlay / push: `warn` (= UI バグの早期検知)
  - message / feature: `silent` (= 未知 kind は plain text fallback、 未登録 feature は disabled)
- **handler.dispatch 内 throw** → console.error + dispatch は null を返す (= 1 件の handler 失敗で chain を止めない)

## 使い方

```js
// features/chat/index.js (= self-register、 これで配線完了)
import { register as registerStream } from '../../registry/streamRegistry.js'
import { handleUserMessage, handleAssistant, handleResult } from './handlers.js'

registerStream('user_message', { dispatch: handleUserMessage })
registerStream('assistant',    { dispatch: handleAssistant })
registerStream('result',       { dispatch: handleResult })

// App.jsx (= import するだけで wiring が effected)
import './features/chat/index.js'
import './features/session-drawer/index.js'
// ... 14 feature 全部 import するだけ

// transport/sse.ts (= subscriber が dispatch を呼ぶ)
import { dispatch } from '../registry/streamRegistry.js'
sseTransport.subscribe(event => dispatch(event))

// overlay 開閉 (= layout / features から呼ぶ)
import { open, close } from '../registry/overlayRegistry.js'
open('drawer')
close('drawer')

// feature 有効判定
import { isEnabled } from '../registry/featureRegistry.js'
if (isEnabled('push-notify')) { /* ... */ }
```

## observability (= W3 DebugPanel / StateInspector)

```js
import { getAllRegistrySnapshots, listRegistryNames } from './_registry.js'

// 全 registry の登録 key 一覧を 1 経路で読む (= debug/state に流す)
const snapshot = getAllRegistrySnapshots()
// → { stream: ['user_message', 'assistant', ...], overlay: ['drawer', 'menu', ...], ... }
```

## 採用 ADR

- **ADR-010** (= Frontend Architecture): registry は features / state / transport / layout から read 経由で呼ばれる。 import direction は boundaries lint で強制 (= features → registry OK、 registry → features NG)
- **ADR-011** (= Contract First): streamRegistry の未定義 event 型は graceful handle、 throw 禁止
- **ADR-017** (= 共通化 pattern): _store.js と同じく _registry.js で 5 重複を撤廃、 observability inspector の入口を 1 経路化

## 関連

- `../domain/` — Event 型 / isKnownEventType (= streamRegistry が import)
- `../state/ui.js` — overlayRegistry が overlay flag を同時に揺らす
- `../transport/sse.ts` — streamRegistry.dispatch を購読 callback で呼ぶ
- `../features/*/index.js` — self-register で配線、 App.jsx は import するだけ
