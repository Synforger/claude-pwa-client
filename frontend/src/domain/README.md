# domain/ — 純粋 TS の core entity 層 (= Hexagonal の内側、 ADR-010)

> **目的**: アプリケーションのドメイン概念 (= Session / Message / Tool / Event) と、 それらに関する純粋な不変条件 / 判定関数だけをここに置く。 React / DOM / EventSource / WebSocket / fetch / localStorage 等の宿主 API には**一切依存しない**。 つまり worker / unit test / 別 entry point から再利用できる。

## 原則 (= 厳守)

- **React import 禁止** (= jsx も hook も使わない)
- **DOM / Web API 禁止** (= localStorage / fetch / EventSource / WebSocket は触らない、 ports/ にだけ依存する側でなく依存される側)
- **副作用禁止** (= pure 関数のみ、 同じ入力 → 同じ出力 + 例外なし)
- **state / ephemeral も持たない** (= 永続化や ephemeral の判断は state/ 配下)
- **唯一許される import**: `../contracts/*.ts` (= codegen 出力の型のみ、 値は import しない方が筋)

## 構成

```
domain/
├── README.md         (本 file)
├── Session.ts        Session entity 型 + 純粋ヘルパ (= newSession / agent_id 検証 / 表示順序)
├── Message.ts        Message / UserMessage / AgentMessage / SystemMessage の判別 union + 純粋関数
├── Tool.ts           ToolUse / ToolResult 型 + 純粋判定関数 (= AgentTool 系の除外判定等)
├── Event.ts          SSE event union + type narrowing (= contracts/sse-events.ts の再利用 + 描画 target 判定)
└── invariants.ts     「同 (sid, uuid) 重複は no-op」 等の純粋判定 (= dedup key、 isPersistable、 sortOrder 等)
```

## 採用 ADR

- **ADR-010** (= Frontend Architecture): hexagonal で features / state / transport が domain に「向かう」 形、 直接の reverse 依存禁止。 import direction lint で強制 (= Phase 6 boundaries)。

## 関連

- `../contracts/` — codegen 出力 (= sse-events / ws-channels / http-endpoints)。 domain はここから型だけ借りる。
- `../ports/` — domain ↔ transport の境界 interface。 domain には依存できる、 逆は不可。
- `../state/` — 真値 / ephemeral を持つ層。 domain の純粋関数を呼ぶ側。
- `../features/` — 機能配線。 domain の純粋判定を経由して描画する。
