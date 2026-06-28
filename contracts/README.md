# contracts/ — front ↔ back の真値スキーマ

> **目的**: claude-pwa-client v2 における HTTP / SSE / WebSocket の **front ↔ back 契約**を yaml で 1 source 化、 codegen で backend pydantic + frontend TypeScript を両側生成、 transport 層を介さない直書きを lint で禁止する構造の根。

## 設計判断 (= ADR 索引)

- **ADR-011** (= Contract First): 自前 yaml 継続 + JSON Schema 2020-12 互換書式に揃える。 OpenAPI / AsyncAPI フル採用は規模で overkill、 ただし将来移行 path を短くする中間案。
- **ADR-012** (= Observability): SSE event envelope に `corr_id` 必須化 (= W3C `traceparent` 互換、 frontend ↔ backend log 結合)。
- **ADR-013** (= PWA Lifecycle): WS channel に heartbeat (= ping/pong) lifecycle 明記、 cache 戦略 / BFCache 対応の前提として lifecycle.yaml を持つ。

## ディレクトリ構造

```
contracts/
├── README.md                       (本 file)
├── schema/                         真値 yaml
│   ├── _meta.json                  全 yaml の meta-schema (= kind dispatch oneOf)
│   ├── sse-events.yaml             17 event 型の field + invariants + 発火 trigger
│   ├── ws-channels.yaml            2 channel の direction + frame + lifecycle
│   ├── http-endpoints.yaml         28 endpoint の method + path + req/res schema + 認証
│   └── lifecycle.yaml              reconnect / bg→fg / kill 復帰の状態遷移
├── codegen/                        生成 script
│   ├── gen-python.py               yaml → backend/jsonl/events_generated.py (pydantic v2)
│   └── gen-types.mjs               yaml → frontend/src/types.d.ts (TypeScript)
└── tests/
    ├── sse-replay/                 contract 検証用 JSONL fixture (= 入力)
    ├── expected/                   期待 SSE frame (= 出力)
    └── negative/                   schema 違反 yaml / 未定義 event jsonl (= ADR-011 negative case)
```

## 真値 yaml の共通形

全 yaml は root に共通 3 field を持つ (= `_meta.json` の oneOf dispatch key):

```yaml
kind: sse-events | ws-channels | http-endpoints | lifecycle
version: "1.0"          # この yaml file の改訂 version (= 内部管理)
schema_version: "1.0"   # protocol 互換性 version (= deprecation policy、 ADR-011)
# 以下、 kind 別の body
```

`kind` で `_meta.json` が分岐 schema を当てる、 同一 ajv コマンドで 4 yaml まとめて validate 可能。

## セットアップ

```bash
cd REDACTED_PATH
npm install   # ajv + ajv-cli + ajv-formats + js-yaml
```

## codegen / validate 起動 (= W1 完了判定)

```bash
cd REDACTED_PATH

# 1. meta-schema validate (= yaml typo 即検知、 ADR-011)
npm run validate
# 内部展開: node codegen/validate.mjs (= ajv API 直叩き、 ajv-cli は脆弱性多 chain で不採用、 0 vulnerabilities)

# 2. codegen (= 両側生成)
python codegen/gen-python.py   # → ../backend/jsonl/events_generated.py
npm run codegen:types          # → ../frontend/src/types.d.ts

# 3. contract test (= backend tests/contracts/)
cd ../backend && pytest tests/contracts/

# 4. negative case (= schema 違反 yaml で codegen exit 1)
cd ../contracts && python codegen/gen-python.py --strict tests/negative/*.yaml  # exit 1 期待
```

## 不変条件 (= ADR-011 invariants 標準化)

- 各 event / channel / endpoint の `invariants:` には機械検証可能な不変条件を列挙 (= 例: 「同一 (sid, uuid) 重複受信は no-op」「corr_id は backend で必ず付与」)
- frontend は schema 未定義 event を **graceful handle** (= log warn + 描画 skip、 throw 禁止)、 schema_version 不一致時も同様 (= Anthropic 流儀、 Vercel AI SDK v4→v5 破壊的変更教訓)
- backend は SSE 生成時に **必ず** `event.corr_id = current_corr_id()` を付与 (= ADR-012)

## v2 構造での位置付け

- `frontend/src/transport/` 経由でしか backend に触れない (= lint `no-restricted-syntax` で `fetch` / `new WebSocket` / `new EventSource` 直書きを transport/ 配下以外で禁止)
- `frontend/src/ports/` interface が contracts/ 生成 type を import (= hexagonal、 ADR-010)
- `backend/jsonl/events.py` は `events_generated.py` の pydantic model を import して shape 保証

## 関連

- 設計書 / ADR / 真値起点 (= interface-current 等) は repo 外の作業 plan に保管。 本 README は repo 内向けに self-contained。
