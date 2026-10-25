# Documentation

claude-pwa-client を **インストールして使うため**の文書です。

## はじめに読むもの

| やりたいこと | どこを見る |
|---|---|
| **インストールして使い始めたい** | [setup/path-a-chat.md](setup/path-a-chat.md) |
| 画面共有も使いたい (任意) | [setup/path-b-screenshare.md](setup/path-b-screenshare.md) |
| 自作のアプリを上部バーから開きたい (任意) | [setup/extensions.md](setup/extensions.md) |
| Windows (WSL2) で動かしたい | [setup/windows-wsl.md](setup/windows-wsl.md) |
| iPhone で、 裏に回っても声で話したい (任意) | [setup/ios-app.md](setup/ios-app.md) |

## 運用ガイド

| 状況 | どこを見る |
|---|---|
| 動かなくなった / 通知が来ない / 画面が固着する | [troubleshooting/troubleshoot.md](troubleshooting/troubleshoot.md) |
| 画面共有 (Sunshine) のメモリリーク対策 | [troubleshooting/sunshine.md](troubleshooting/sunshine.md) |

## 設定リファレンス

| 知りたいこと | どこを見る |
|---|---|
| `backend/config.json` の各フィールド / `frontend/.env.local` | [reference/config.md](reference/config.md) |
| backend が永続化する JSON ファイルの中身 / バックアップ範囲 | [reference/data-schemas.md](reference/data-schemas.md) |
| pdf・Office・tif・md を、 path のタップで頁として開きたい | [reference/documents.md](reference/documents.md) |
| タブの中の Claude どうしで連絡させたい | [reference/agent-messages.md](reference/agent-messages.md) |
| 長くなった会話を自動で締めて、 新しい会話に入れ替えたい | [reference/rollover.md](reference/rollover.md) |
| タブの中の Claude に、 仕事を渡す別のタブを立てさせたい | [reference/child-sessions.md](reference/child-sessions.md) |
| エージェントの階層ごとのタブを、 最初から一覧に並べておきたい | [reference/tier-tabs.md](reference/tier-tabs.md) |
| エージェントと声で会話したい / 返事を声にしたい | [reference/voice.md](reference/voice.md) |
| Mac のエージェントに iPhone の中を読ませたい / iPhone で操作させたい | [reference/device-ops.md](reference/device-ops.md) |

---

## 開発に参加したい人向け

設計の中身 (= backend / frontend の構成、 SSE / WebSocket プロトコル、 拡張ポイント) は [internals/](internals/) を参照。 PWA を**使うだけ**なら読む必要はありません。
