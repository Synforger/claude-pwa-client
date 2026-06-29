# Docs

claude-pwa-client の構造・仕様・運用 doc 群。 真値は code 内 docstring、 本 doc は **「全体地図 + 第三者が hour 単位で詰まる箇所の構造説明」** に絞る (= drift を増やさない、 増殖防止)。

## 増殖防止 rule

新 doc 追加判断軸 = **第三者が hour 単位で詰まる構造説明か**。 yes なら追加、 no は該当 file の docstring 強化で済ます。 「念のため doc 化」 は禁止 (= 真値分散の温床)。

## カテゴリ

### `architecture/` — 全体設計
- [`overview.md`](architecture/overview.md) — backend サブパッケージ責務 / 依存方向 DAG / `SessionState + asyncio.Lock` / frontend W2 構成 (= 19 features + 6 store + 5 registry)
- [`state-stores.md`](architecture/state-stores.md) — frontend `state/` 6 store の責務 + どの feature が subscribe するか
- [`extending.md`](architecture/extending.md) — 新 tool / 新 SSE event / 新 modal / 新 account / 新 push channel を足す手順 (= 順序厳守)

### `protocol/` — backend ↔ frontend wire 真値
- [`streams.md`](protocol/streams.md) — 4 SSE + 2 WS の責任分担 + `/jsonl/stream/*` の event wire shape (= 旧 streams + sse-event-shape 統合)

### `setup/` — 利用者向け install
- [`path-a-chat.md`](setup/path-a-chat.md) — 最小構成 (チャット + 通知)
- [`path-b-screenshare.md`](setup/path-b-screenshare.md) — Sunshine + moonlight-web-stream で画面共有追加
- [`windows-wsl.md`](setup/windows-wsl.md) — Windows (WSL2) ホスト向け

### `ops/` — 運用 / トラブル対応
- [`sunshine.md`](ops/sunshine.md) — Sunshine watchdog runbook (= backend から外出しした phys_footprint リーク対策)
- [`troubleshoot.md`](ops/troubleshoot.md) — Tailscale 証明書 / SW 失効 / セッション復旧 / encoder hang 等

### `reference/` — 仕様 / schema
- [`config.md`](reference/config.md) — `backend/config.json` / `frontend/.env.local` / VAPID 鍵
- [`data-schemas.md`](reference/data-schemas.md) — `backend/data/*.json` + `backend/secrets/*.json` の schema 全件 + backup 対象範囲
