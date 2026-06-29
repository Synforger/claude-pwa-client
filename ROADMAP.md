# Roadmap

このリポは個人プロジェクトです。 「このリポは今安定して使えるのか / 何が作りかけか」 を判断するための一覧。

## いま使えること

- Tailscale 経由でスマートフォンから Claude Code を操作 (= チャット + 通知)
- 複数セッション並走 + バックグラウンド継続
- Web Push 通知 (iOS 16.4+ / Android、 `AskUserQuestion` や処理完了で発火)
- 添付ファイル送信 / 履歴永続化 / 会話のフォーク
- ステータスバー (モデル / 残予算 / 使用率)
- マルチアカウント (個人 / 会社 を切替)
- デスクトップ画面共有 (任意、 [setup/path-b-screenshare.md](docs/setup/path-b-screenshare.md))

## 今後やる予定

- iOS native の画面共有 (= 音声修正 / PiP / 入力プラグイン / 通知 extension)。 ブラウザ経由の Path B は既に動作、 これは AltStore 配布前提の native アプリ版

## 検討中 (= まだ着手していない)

- メッセージ履歴の真値 store 化 (= 現状は localStorage を主、 内部 store はミラー)
- 画面共有関連の検出機構のチューニング

## 採用しない方針

- GitHub Issues / Actions (= 個人運用、 ローカル `.githooks/` で品質ゲートを完結)
- SECURITY.md 以外の `.github/` ファイル (= ISSUE_TEMPLATE / CONTRIBUTING.md は collaborator ゼロで形骸化)

## バグ報告 / 機能要望

- セキュリティ脆弱性: [SECURITY.md](SECURITY.md) の GitHub Security Advisories から (公開 issue は使わない)
- 機能要望 / 一般バグ: GitHub Issues は無効化されています。 必要に応じて Pull Request を歓迎します
