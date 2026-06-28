# transport/ — backend 接続の唯一の入口

> **目的**: `fetch` / `new EventSource` / `new WebSocket` を呼ぶ場所をここに 1 箇所にまとめ、 features / layout / state / domain がそれを経由する形にする。 features 層は ports/* interface だけ知っていれば良く、 transport 実装の入れ替え (= mock / 別実装 / 将来の WebTransport 移行) が安全になる。

## file 構成

```
transport/
├── README.md         (本 file)
├── http.ts           HttpClient 実装 (= apiFetch + corr_id 付与 + timeout + idempotent retry + signal 合成)
├── sse.ts            SseTransport 実装 (= 単一 EventSource + offsets localStorage 永続化)
├── ws-pty.ts         PtyTransport 実装 (= /ws/pty/{sid} + heartbeat 25s/60s + bytes 主経路)
├── ws-views.ts       ViewsTransport 実装 (= /views/ws + visible 中のみ接続)
├── lifecycle.ts      Page lifecycle listener (= visibility / pagehide / pageshow / freeze)
└── correlation.ts    W3C traceparent / corr_id 共通 helper + 直近 corr_id ↔ HTTP 記録
```

## 採用 ADR

- **ADR-010** (= Frontend Architecture): hexagonal、 ports/ → transport/ への片方向 import direction を eslint-plugin-boundaries で強制 (= Phase 6)
- **ADR-012** (= Observability): W3C traceparent 自前生成 + X-Correlation-Id 互換 header 付与、 全 response の status を corr_id ひもづけで記録
- **ADR-013** (= PWA Lifecycle): heartbeat ping 25s + pong timeout 60s force-reconnect、 beforeunload 廃止、 pageshow.persisted で BFCache 復帰検知 → transport rebuild

## 使い方

```ts
// features 層 / hooks 層からは ports interface だけ知ってる前提
import { sseTransport } from '../transport/sse.ts'
import { httpClient } from '../transport/http.ts'

const unsubscribe = sseTransport.subscribe((event) => {
  // event は AnySseEvent 型 (= contracts/sse-events.ts)、 sid + corr_id 必須
  if (event.type === 'user_message') { /* ... */ }
})

const res = await httpClient.apiFetch('/sessions', { method: 'POST', jsonBody: { agent_id: 'default' } })
```

```ts
// アプリ起動時 (= main.tsx / App.tsx) 1 回だけ
import { installListeners } from './transport/lifecycle.ts'
installListeners()
```

## 直書き禁止 (= Phase 6 lint 強制)

`transport/` 配下以外で `fetch(` / `new WebSocket` / `new EventSource` の直書きを **eslint-plugin no-restricted-syntax で禁止**。 違反すると lint で fail。 transport を増やしたければ本ディレクトリに新規 file を追加して ports/ interface を実装する。

## 並列性 / 唯一性

- `sseTransport` は singleton、 1 アプリ 1 EventSource (= F-15 統合、 タブ切替 0 遅延の前提)
- `ptyTransport` は sid 単位の Map で WebSocket を持ち、 同 sid 再 connect は idempotent
- `viewsTransport` は singleton、 1 接続、 activeSid 変化時に即送信
- `httpClient` は singleton、 全 fetch を 1 経路に統合

## 関連

- `../ports/` interface 契約 (= 本実装が implements する)
- `../contracts/` codegen 出力 type (= sse-events / ws-channels / http-endpoints)
- backend SSE pump (= `_inject_envelope`) が sid + corr_id を必ず付ける契約は ADR-012 + contracts/schema/sse-events.yaml の global required で担保
