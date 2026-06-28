# contracts/tests/ — schema 動作確認 fixture

> **目的**: W1 Phase 3 (= backend `tests/contracts/`) で「実 SSE 出力 ⊂ schema」 を pytest する時の入力 / 期待 fixture。 Phase 1 では fixture 配置のみ、 照合 logic は Phase 3 で書く。

## ディレクトリ

```
tests/
├── README.md           (本 file)
├── sse-replay/         入力 JSONL (= backend が処理する 1 行ずつの fixture)
├── expected/           対応する期待 SSE event 列 (= JSON array)
└── negative/           schema 違反 fixture (= validate exit 1 を期待する yaml + 未定義 event jsonl)
```

## scenario 命名

`<area>-<case>.jsonl` 形式。 area = chat / tool / system / error 等、 case = basic / multi-turn / refusal 等。 `expected/<同名>.json` で対応付け。

## positive scenario (= sse-replay/)

| file | 内容 |
|---|---|
| chat-basic.jsonl | 1 user 発話 → 1 assistant 応答 (= 単純な golden path) |

## negative scenario (= negative/)

| file | 期待挙動 |
|---|---|
| missing-events-key.yaml | sse-events kind なのに events key を欠落、 meta-schema validate で exit 1 |
| unknown-event-type.jsonl | type: "weird_event_we_dont_know" を含む、 frontend graceful handle (= log warn + 描画 skip、 throw 禁止) を確認する fixture |

## negative validate 確認 (= W1 Phase 3 着地後)

```bash
# 期待: exit code 1 (= meta-schema 違反)
cd contracts && node codegen/validate.mjs --strict 2>&1 | grep -q FAIL && echo "expected fail OK"

# 期待: backend pytest が unknown event を skip + warn log、 throw しない
cd ../backend && pytest tests/contracts/test_unknown_event.py
```
