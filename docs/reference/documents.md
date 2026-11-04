# 資料を開く (pdf・Office・tif)

会話・メモ・ファイルの木・お気に入りの path をタップすると、 画像と HTML のほかに、 次の資料も画面で開けます。

| 種類 | 拡張子 | 見え方 |
|---|---|---|
| PDF | `.pdf` | 頁ごとの画像を縦に並べた頁 |
| Office | `.pptx` `.xlsx` `.docx` | PDF に変えてから、 同じく頁の画像 |
| 画像 (複数頁も可) | `.tif` `.tiff` | 全頁を頁の画像に |

開いた file は backend が頁の画像に変えて返します。 変換には時間が掛かるので、 初めて開く時は「変換しています」 の
画面が出て、 終わると自動で頁に切り替わります。 変換できなかった時は、 その理由が 1 行で出ます (「もう一度試す」 で
作り直せます)。 変換した物は元の file の中身が変わるまで控えとして持つので、 2 回目からは待たずに開きます。
頁に出る文言 (= 変換の画面・理由・下の図の枠) は、 ブラウザの言語 (`Accept-Language`) の先頭が日本語なら日本語、
それ以外は英語です。

タップした資料は、 iPhone と iPad では client の中のプレビュー (= 会話の上の枠) で開きます。 Mac・PC の画面で会話と
メモの path を押した時は、 下の「Mac で開く path」 のとおり Mac のアプリで開きます。 HTML だけはどの端末でも別で、 OS の
既定のブラウザで開きます (iPhone のホーム画面の PWA は、 既定のブラウザへ渡す口が無いので Safari で開きます)。
[`page_origin`](config.md) の folder の中の資料は、 その HTML と同じ origin で頁を配ります。

別の道具 (= ボードの拡張など) が `/file/open` で HTML 以外の file (= 資料・画像・Markdown・コード) をブラウザの
タブとして開いた時は、 頁を描かずにそのタブを client の画面へ回し、 同じプレビューの枠で開きます (= ✕ で会話へ戻れる。
ブラウザが付ける `Sec-Fetch-Dest` が `document` の要求を回す)。

ブラウザで開いた HTML のページの中のリンクは、 client の画面へ回さず、 そのブラウザの中で開きます。

| リンクの先 | 開き方 |
|---|---|
| HTML のページ | そのページ (= 同じ sandbox。 `page_origin` の folder の中なら同じ origin) |
| 画像・動画・音声・JSON・CSV・CSS・JS・フォント | ブラウザがそのまま見せる |
| 資料 (= PDF・Office・tif) | 上の頁の画像の頁 |
| Markdown・コード・そのほかの文字の file | 文字のまま (= Markdown は描かない) |
| 文字でない、 配る形の決まっていない file | ダウンロード |
| web のページ | そのページ |

`target="_blank"` のリンクは新しいタブで開きます。 戻るのはブラウザの戻る操作です。 iPhone のホーム画面の PWA の
プレビューの枠の中で開いたページでは、 リンクの先も同じ枠の中で開きます。

## Mac で開く path

会話とメモに書かれた path は、 Mac・PC の画面で押すと、 backend が動いている Mac で、 Finder でダブルクリックした時と
同じに開きます。

| 押した path | 開き方 |
|---|---|
| Markdown (= `.md` `.markdown`) | client の中のプレビュー (= 中の path のリンクがそのまま押せる) |
| HTML | ブラウザ (= 上のとおり) |
| フォルダ (= 末尾の `/` の有無は問いません) | Finder で開く |
| それ以外の file (= コード・PDF・画像・Office・動画など) | その Mac の既定のアプリ (= `.py` は `.py` を開くアプリ) |
| 走らせる物 (= `.app` `.command` `.pkg` `.dmg` などと、 拡張子のあるフォルダ、 拡張子が無く実行の権限のある file) | 走らせず、 親のフォルダの中で選んだ状態 |
| 開くアプリの無い file | 親のフォルダの中で選んだ状態 |

開ける範囲は下の「開ける範囲」 と同じです。 押したのが backend のある Mac とは別の機械の画面でも、 開くのは backend の
ある Mac です。

iPhone と iPad、 macOS でない backend、 ファイルの木とお気に入りでは、 OS へ渡さず、 フォルダはファイルの木で、 file は
プレビューで開きます。 プレビューは、 中身が文字でない file (= 先頭の 8000 byte に NUL を含む。 git が差分を出すかを
決めるのと同じ見方) を「この画面では開けないファイルです」 と出します。

## 閉じて会話へ戻る

| 開き方 | 戻る口 |
|---|---|
| 資料・画像・Markdown (= プレビューの枠) | 枠の ✕ (= 枠の中で別の頁へ移った後も、 同じ ✕ で会話へ戻ります) |
| HTML (ブラウザ) | そのタブを閉じる (= ブラウザの操作) |
| HTML (iPhone の app) | 既定のブラウザから app へ戻る (= iPhone の操作) |
| HTML (ホーム画面の PWA) | Safari から PWA へ戻る (= iPhone の操作) |

資料の頁の中のリンクで別の資料や頁へ移っても、 戻る口は同じです。 `page_origin` の folder の頁が、 枠の外の画面を
別の頁へ移すこと (`target="_top"` など) は封じています ([config.md](config.md))。

## 開ける範囲

HTML と同じです (`/file/view` と同じ検査)。

- 読めるのは HOME の下だけで、 鍵・認証情報・シェルの初期化 file などの deny list に当たる path は開きません
- `page_origin` の folder の外の file は、 その port からは開きません (symlink で外へ出る物も含む)
- 1 file 50 MB まで
- 開く前の変換の command には、 path を引数としてそのまま渡します (shell は通りません)

## HTML のページから資料を開く

資料の頁は、 元の file と同じ path の URL で配ります。 `page_origin` の folder の HTML から、 資料へ相対のリンクを
書けば開きます。

```html
<a href="../materials/spec.pdf">仕様書</a>
<a href="notes/plan.md#scope">計画の「範囲」</a>
```

頁の画像は、 資料の URL に `?page=<番号>&v=<版>` を付けて読みます。

## 必要な道具

backend を動かす機械に、 次の command が要ります (= 使う種類の分だけ。 無い時は変換の画面にその command の名前が出ます)。

| 種類 | command | 入れ方 (macOS) |
|---|---|---|
| PDF・Office・tif の頁の画像 | `pdftoppm` (poppler) | `brew install poppler` |
| Office | `soffice` (LibreOffice) | `brew install --cask libreoffice` |
| tif | `tiff2pdf` (libtiff。 poppler と一緒に入ります) | `brew install libtiff` |

tif は `tiff2pdf` が無い時、 macOS の `sips` で 1 頁目だけを画像にします。 command は `PATH` に加えて
`/opt/homebrew/bin`・`/usr/local/bin`・`/Applications/LibreOffice.app/Contents/MacOS` も探します (= 常駐の
`PATH` が短くても動きます)。

## 設定: 控えの置き場と大きさ

`backend/config.json` の `documents` (任意)。 書かなければ既定で動きます。

```json
"documents": {
  "cache_dir": "~/.claude-pwa-client/document-cache",
  "cache_max_mb": 1024
}
```

| 項目 | 意味 | 既定 |
|---|---|---|
| `cache_dir` | 変換した頁の画像の置き場 | `~/.claude-pwa-client/document-cache` |
| `cache_max_mb` | 置き場の大きさの上限 (MB)。 超えたら、 最後に開いてから長い物から消す | `1024` |

- 控えは元の file の実体の path・大きさ・更新時刻ごとに 1 つです。 中身が変わった file は作り直し、 同じ file の
  古い控えは消えます
- 頁の画像は 130 dpi の JPEG (= A4 で幅 約 1075 px) です。 文字中心の頁は 1 頁 50 KB 前後で、 図や写真の多い頁はそれより大きくなります。 置き場の大きさは、 開く資料の頁数に合わせて決めてください
- 上限より大きい資料 1 つは、 その資料の頁だけを残して置き場に持ちます (= 開いた直後の資料は消えません)
- 変換は同時に 2 つまでで、 1 つの command は 300 秒で止めます (= 止めた時は理由に出ます)
- 書き損じた欄は起動ログに指摘を出し、 既定に戻します
