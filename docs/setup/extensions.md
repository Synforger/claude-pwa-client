# 拡張を載せる (任意)

別のアプリ (= 自分で作った Web UI) を、 PWA の上部バー右端の 🧩 から開ける**拡張**として載せる手順。
拡張はチャットの上に帯で開き、 開いている間もチャット入力欄はそのまま使える。 閉じても拡張の
画面は裏で動き続ける (= 音の再生や接続が切れない)。

拡張の中身は claude-pwa-client の repo に入れない。 本体が知るのは「拡張の名前・アイコン・id」
だけで、 拡張への経路は Tailscale Serve が持つ。

## 仕組み

```
[Smartphone]                        [Host machine]
  PWA ── https://<host>/ ─────────▶ backend (claude-pwa-client)
   └ iframe ── https://<host>/ext/<id>/ ──▶ 拡張のプロセス (127.0.0.1:<port>)
                        ↑ Tailscale Serve が /ext/<id> を転送
```

- 拡張は `https://<host>/ext/<id>/` に載る (= PWA と同一オリジン。 証明書 / CORS / Cookie の設定は要らない)
- PWA は起動時に `GET /extensions` で一覧を取り、 各拡張の `/ext/<id>/` に `HEAD` を 1 回投げる。
  2xx が返った拡張だけ 🧩 の一覧に並ぶ (= 1 本も届かなければ 🧩 自体が出ない)
- 本体は拡張に何も渡さない (= token もテーマも渡さない)。 認証が要るなら拡張が自分で持つ

## 1. 拡張を用意する

拡張は HTTP で自分の画面を配る 1 プロセス。 満たすことは 3 つ:

1. **`127.0.0.1` で待ち受ける** (= tailnet 側の入口は Tailscale Serve の 1 つだけにする)
2. **`/` への `GET` と `HEAD` に 2xx を返す** (= `HEAD` が通らないと PWA はボタンを出さない)
3. **画面から自分を呼ぶ URL は相対で書く** (= `fetch('api/status')`、 `<audio src="stream.ogg">`)。
   `/` 始まりで書くと `/ext/<id>/` の外に出て PWA の backend に当たる

Tailscale Serve は `/ext/<id>` を取り除いてから転送するので、 拡張のプロセスには `/ext/<id>/api/status`
が `/api/status` として届く (= 拡張は自分がどこに載っているかを知らなくてよい)。

## 2. Tailscale Serve に載せる

PWA 本体を `/` に載せ済み (= [path-a-chat.md](path-a-chat.md)) の前提で、 拡張ごとに 1 行:

```bash
tailscale serve --bg --set-path=/ext/<id> http://127.0.0.1:<port>
```

`tailscale serve status` で `/ext/<id>` が並んでいれば載っている。

## 3. `backend/config.json` に宣言する

```json
"extensions": [
  { "id": "<id>", "title": "<name>", "icon": "🎛" }
]
```

- `id` (必須): 英小文字・数字・ハイフンの 32 文字まで (= 先頭はハイフン不可)。 Tailscale Serve の
  `/ext/<id>` と揃える
- `title` (任意): ボタンの説明と iframe の title。 未指定なら `id`
- `icon` (任意): 🧩 の一覧で名前の前に出す文字 (= 絵文字 1 つを想定)。 未指定なら 🧩

書いたら backend を再起動する (= `task restart`)。 不正な entry はその 1 件だけ捨てられ、 理由が
起動ログに `runtime check: config.extensions[<n>] dropped: ...` として出る。

## 使い方

- 上部バー右端の 🧩 → 一覧から選ぶと開く / 開いている拡張をもう一度選ぶと畳む。 畳んでも拡張は動き続ける
- 開けるのは同時に 1 つ (= 別の拡張や 🖥 画面共有を開くと、 今の拡張は畳まれる)
- 帯の高さは画面の 40% (= 下にチャットと入力欄が残る)。 拡張の画面は、 この高さにスクロールなしで収まる作りにしておくと使いやすい
- 帯の右上の ⛶ で全画面

## 詰まった時

| 症状 | 見るところ |
|---|---|
| 🧩 の一覧に出ない | `curl -I https://<host>/ext/<id>/` が 2xx か (= 拡張のプロセス / Tailscale Serve の行)。 `curl https://<host>/extensions` に載っているか (= `config.json` の書き損じは起動ログ) |
| 開くと PWA 本体の画面が出る / 404 | 拡張の画面が `/` 始まりの URL で自分を呼んでいる (= 相対 URL にする) |
| 開いた直後だけ動いて、 閉じると止まる | 拡張の側で `visibilitychange` 等を見て止めていないか (= 本体は iframe を破棄しない) |
