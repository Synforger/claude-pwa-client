# Internals (= contributor / 開発参加者向け)

PWA を**使うだけ**なら読む必要はありません。 [../README.md](../README.md) に戻ってください。

開発に参加する / コードに手を入れる場合の参照資料。

| 内容 | file |
|---|---|
| backend サブパッケージ責務 / 依存方向 / frontend の構成 (= layout / features / state / registry の役割) | [architecture/overview.md](architecture/overview.md) |
| frontend の state store の責務 + どの component が subscribe するか | [architecture/state-stores.md](architecture/state-stores.md) |
| 新しい tool / SSE event / overlay / account / push channel を足す手順 | [architecture/extending.md](architecture/extending.md) |
| SSE / WebSocket 経路の責任分担 + event の wire shape | [protocol/streams.md](protocol/streams.md) |

## 開発フロー (= ローカルが真値、 CI は鏡)

品質ゲートの実体は全部ローカル (= `.githooks/` + Taskfile + `.tooling/`) にあり、 offline で完結する。 GitHub Actions は [`ci.yml`](../../.github/workflows/ci.yml) 1 本だけで、 同じ `task ci` を pull request で走らせる薄い trigger (= 外部 contributor がゲート一式を持たなくても status check が付く)。 CI にしか無い検査は作らない。 clone 後の活性化は `task setup` に含まれる。

**`git config --local core.hooksPath .githooks` は実行しない。** git が使う `core.hooksPath` は 1 つだけで、ローカル指定はマシン全体のガード (= global `core.hooksPath`) を丸ごと上書きする。 `.githooks/` はガード側が委譲実行するので、ローカル指定すると得るものが無いまま commit message の個人識別子スキャンだけを失う。 マシン全体のガードが無い環境では `task setup` が自動でローカルにフォールバックし、その旨を警告する。

これで commit 時に以下が staged 範囲に応じて自動で走る (= 手動で全件回したい時は `task lint` / `task test` / `task anon:scan` / `task audit`):

1. **anon-scan** (= 個人識別子の混入チェック、 全 commit)
2. **flake8** (= staged Python のみ、 構文 / 未定義名 / f-string 等の致命チェック)
3. **eslint** (= staged JS/JSX/TS/TSX のみ、 `frontend/node_modules/eslint` 存在時)
4. **gitleaks** (= staged 分の secret パターン検知、 RSA / SSH 秘密鍵 / token 形式)
5. **audit-w2-residue** (= `frontend/src/state/` `features/` `layout/` `*.css` のいずれかが staged の時のみ、 状態二重管理 / orphan setter / CSS absolute anchor を検出)

意図的に gate を回避したい時は `--no-verify`。 偽陽性は `.tooling/local-ci/audit-w2-residue-allowlist.txt` に追記。
