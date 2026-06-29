# Roadmap

claude-pwa-client の進行中・検討中・不採用の作業を可視化する。 主に開発者 (= 自分) の整理用 + 他人が「これ作りかけか、 安定か、 取りに行くか」 判断するための入口。

> 個人プロジェクト (= collaborator ゼロ運用) なので GitHub Issues は使わない方針。 ここに方向性だけ宣言、 細かい todo は手元管理。

## 安定 (= ready to use)

- **chat + 通知** (Path A): 複数セッション並走 / SSE 逐次表示 / Web Push (iOS 16.4+) / AskUserQuestion / バックグラウンド継続
- **W2 architecture overhaul**: AppShell 解体 → Layout 55 行 + 19 features + 6 state stores + 5 registries (= 2026-06-29 着地、 28 PR sweep)
- **PTY 起動の自動化**: chat view 単独で `task setup → task run` → 新規タブ作成 / セッション終了 (restart) で `launch_alias` が自動投入される (= 2026-06-29 race fix)
- **配布**: synforger/claude-pwa-client public repo、 ローカル `.githooks/` 一本化 (= GitHub Actions 不使用)

## 進行中 / 検討中

- **iOS native (画面共有)** = Path B (Sunshine + moonlight-web-stream) の iOS PWA 完成に向けた残 phase 群:
  - Phase 3 = audio fix (= 音声 streaming 詰まり)
  - Phase 4 = UI 統合
  - Phase 5 = PiP (Picture in Picture)
  - Phase 5.5 = 入力 plugin (= touch → mouse / keyboard 変換)
  - Phase 6 = 通知 extension (= Live Activities / Widget)
  - 各 phase で iOS 実機 + Xcode archive 必須、 AltStore 経由配布
- **messages store の真値逆転検討**: 現状 `localStorage` を真値、 `state/messages.js` は mirror。 store を真値に倒すと `useChatStorage` の永続化境界も hydrate 経由に書き直す大改修 (= ADR-026 後継議論として残置)
- **W2 residue detector の精度向上**: `audit-w2-residue.py` の false positive (= moonlight 等の semantic 区別) を allowlist でなく structural に判定する余地 (= 現状 allowlist で実害ゼロのため優先度低)

## 公開向け file (= 当面追加しない方針)

- `SECURITY.md` / `.github/ISSUE_TEMPLATE` / `CONTRIBUTING.md` = collaborator ゼロ運用なので形骸化リスク、 追加しない。 将来 PR / issue が来始めたら判断。
- GitHub Actions workflow = 不採用 (= ローカル `.githooks/` 一本化、 詳細は README § 開発フロー)

## 不採用 / 撤回済

- chat view 起動 alias config 化 = 当初検討したが既存 `config.json::agents[*].launch_alias` で十分、 重複ゼロ
- `transport.js` state store = W2 Phase J-12 で dead 削除 (= 全 setter orphan、 接続生存 signal は `transport/lifecycle.js::registerConnection` に集約)

## 他人が contribute したい場合

GitHub Issues は使ってないので、 PR を直接送ってもらえれば検討します。 大物 (= 数百行 diff / architecture 変更) は事前に discussion で意図確認推奨。 backend は POSIX 前提 (PTY / tmux / lsof)、 Windows ネイティブは対象外で WSL2 経由。
