# Documentation

claude-pwa-client を **インストールして使うため**の文書です。

## はじめに読むもの

| やりたいこと | どこを見る |
|---|---|
| **インストールして使い始めたい** | [setup/path-a-chat.md](setup/path-a-chat.md) |
| 画面共有も使いたい (任意) | [setup/path-b-screenshare.md](setup/path-b-screenshare.md) |
| Windows (WSL2) で動かしたい | [setup/windows-wsl.md](setup/windows-wsl.md) |

## 運用ガイド

| 状況 | どこを見る |
|---|---|
| 動かなくなった / 通知が来ない / 画面が固着する | [ops/troubleshoot.md](ops/troubleshoot.md) |
| 画面共有 (Sunshine) のメモリリーク対策 | [ops/sunshine.md](ops/sunshine.md) |

## 設定リファレンス

| 知りたいこと | どこを見る |
|---|---|
| `backend/config.json` の各フィールド / `frontend/.env.local` | [reference/config.md](reference/config.md) |
| backend が永続化する JSON ファイルの中身 / バックアップ範囲 | [reference/data-schemas.md](reference/data-schemas.md) |

---

## 開発に参加したい人向け

設計の中身 (= backend / frontend の構成、 SSE / WebSocket プロトコル、 拡張ポイント) は [internals/](internals/) を参照。 PWA を**使うだけ**なら読む必要はありません。
