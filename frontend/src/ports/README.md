# ports/ — domain ↔ transport の境界 interface (= Hexagonal、 ADR-010)

> **目的**: backend 接続の **interface 契約**だけをここに置く。 transport/ 配下の実装が ports/* を `implements` する形にして、 (= 1) mock 差替で contract test / unit test 可能、 (= 2) 将来 transport 切替 (= 例: WebSocket → WebTransport) を安全化、 (= 3) domain / features 層が transport 実装に直接依存しない。

## 構成

```
ports/
├── README.md         (本 file)
├── SseTransport.ts   /jsonl/stream/all を購読する interface
├── PtyTransport.ts   /ws/pty/{sid} の interface (= bytes + control + heartbeat)
├── ViewsTransport.ts /views/ws の interface (= activeSid + stop intent)
└── HttpClient.ts     fetch wrapper の interface (= corr_id + timeout + retry)
```

## 設計判断 (= ADR 索引)

- **ADR-010** (= Frontend Architecture): domain (= 純粋 TS、 React 非依存) + ports (= 本ディレクトリ) + transport (= adapter) の 3 層、 import direction を eslint-plugin-boundaries で強制
- **ADR-012** (= Observability): corr_id (= W3C traceparent 互換) は HttpClient header / SseTransport event payload で必ず流す
- **ADR-013** (= PWA Lifecycle): PtyTransport は heartbeat ping/pong 25s/60s を契約に含める、 ViewsTransport は visible 中のみ接続

## 使い方

```ts
// features/chat/handlers.ts (= 例)
import type { SseTransport } from '../ports/SseTransport.ts'
import type { AnySseEvent } from '../contracts/sse-events.ts'

export function wireChatHandlers(sse: SseTransport) {
  return sse.subscribe((event: AnySseEvent) => {
    // features 層は SseTransport 実装を知らない、 interface だけ依存
  })
}

// transport/sse.ts (= 実装側)
import type { SseTransport } from '../ports/SseTransport.ts'
class SseTransportImpl implements SseTransport { ... }
```

## 関連

- domain/ — React 非依存、 純粋 TS の Session / Message / Event 型 (= W2 で起こす)
- transport/ — ports/* の実装、 fetch / EventSource / WebSocket を呼ぶ唯一の場所 (= Phase 5 で起こす)
- contracts/*.ts — codegen 出力の event / channel / endpoint 型 (= Phase 5 で配置、 ADR-015 / ADR-016)
