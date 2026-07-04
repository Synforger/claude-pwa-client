# ブランチ保護ルール設定ガイド

## 概要

このドキュメントでは、`scripts/setup-branch-protection.sh`スクリプトを使用したブランチ保護ルールの自動設定と、フォークを使用した手動検証手順について説明します。

## 自動設定スクリプトの使用方法

### 前提条件

- GitHub CLI (`gh`) がインストールされ、認証済みであること
- 対象リポジトリへの管理者権限があること

### 実行方法

```bash
# リポジトリのルートディレクトリで実行
./scripts/setup-branch-protection.sh

# 環境変数で設定をカスタマイズ（オプション）
GITHUB_OWNER="your-org" GITHUB_REPO="your-repo" ./scripts/setup-branch-protection.sh
```

### 設定される保護ルール

スクリプトは以下の2つのブランチパターンに対して保護ルールを設定します：

1. **パターン**: `[dm][ea][vi][!o]*`
   - 対象: `main`, `develop`, `dev`, `dmain` など
2. **パターン**: `*/[dm][ea][vi][!o]*`  
   - 対象: `feature/main`, `hotfix/develop` など

### 保護設定内容

- ✅ **Require a pull request before merging** (PR必須)
- ✅ **Require status checks to pass before merging** (ステータスチェック必須)
  - 必須チェック: `build` (GitHub Actionsワークフロー)
- ✅ **Require branches to be up to date before merging** (最新状態必須)
- ✅ **Enforce admins** (管理者にも適用)
- ❌ **Allow force pushes** (強制プッシュ禁止)
- ❌ **Allow deletions** (削除禁止)

## フォークを使用した手動検証手順

### 1. テスト用フォークの作成

1. GitHubでテンプレートリポジトリをフォーク
2. フォークしたリポジトリをローカルにクローン
   ```bash
   git clone https://github.com/YOUR_USERNAME/rd-prj-template.git
   cd rd-prj-template
   ```

### 2. ブランチ保護スクリプトの実行

```bash
# スクリプトを実行してブランチ保護を設定
./scripts/setup-branch-protection.sh
```

### 3. GitHub UIでの設定確認

1. フォークしたリポジトリのGitHub画面を開く
2. **Settings** → **Branches** → **Branch protection rules** に移動
3. 以下のルールが作成されていることを確認：
   - `[dm][ea][vi][!o]*`
   - `*/[dm][ea][vi][!o]*`

### 4. 保護ルールの動作テスト

#### テスト1: 直接プッシュの禁止確認

```bash
# mainブランチに直接コミットを試行（失敗するはず）
git checkout main
echo "test" >> test.txt
git add test.txt
git commit -m "Direct commit test"
git push origin main  # これは失敗するはず
```

#### テスト2: PR経由でのマージテスト

```bash
# フィーチャーブランチを作成
git checkout -b test-branch-protection
echo "PR test" >> test.txt
git add test.txt
git commit -m "Test PR workflow"
git push origin test-branch-protection

# GitHub UIでPRを作成し、以下を確認：
# - ステータスチェック（build）が必須になっている
# - マージ前にブランチの最新化が必要
# - 管理者でもPRが必須
```

### 5. 検証チェックリスト

- [ ] ブランチ保護ルールが正しく作成されている
- [ ] 直接プッシュが禁止されている
- [ ] PRが必須になっている
- [ ] ステータスチェック（build）が必須
- [ ] ブランチの最新化が必須
- [ ] 管理者にも保護ルールが適用されている

## トラブルシューティング

### よくある問題

1. **権限エラー**: リポジトリの管理者権限を確認
2. **GitHub CLI認証エラー**: `gh auth status` で認証状態を確認
3. **GraphQL API エラー**: REST API フォールバックが動作するか確認

### ログの確認

スクリプト実行時の詳細ログを確認し、エラーメッセージを参照してください。

## 関連リンク

- [GitHub Branch Protection API](https://docs.github.com/en/rest/branches/branch-protection)
- [GitHub GraphQL API](https://docs.github.com/en/graphql/reference/mutations#createbranchprotectionrule)
- [GitHub CLI Documentation](https://cli.github.com/manual/)
