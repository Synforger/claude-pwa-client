# 資料を開く (pdf・Office・tif・Markdown)

会話・メモ・ファイルの木・お気に入りの path をタップすると、 画像と HTML のほかに、 次の資料も画面で開けます。

| 種類 | 拡張子 | 見え方 |
|---|---|---|
| PDF | `.pdf` | 頁ごとの画像を縦に並べた頁 |
| Office | `.pptx` `.xlsx` `.docx` | PDF に変えてから、 同じく頁の画像 |
| 画像 (複数頁も可) | `.tif` `.tiff` | 全頁を頁の画像に |
| Markdown | `.md` `.markdown` | HTML に変えた頁 (下の「Markdown」) |

開いた file は backend が頁の画像に変えて返します。 変換には時間が掛かるので、 初めて開く時は「変換しています」 の
画面が出て、 終わると自動で頁に切り替わります。 変換できなかった時は、 その理由が 1 行で出ます (「もう一度試す」 で
作り直せます)。 変換した物は元の file の中身が変わるまで控えとして持つので、 2 回目からは待たずに開きます。
頁に出る文言 (= 変換の画面・理由・下の図の枠) は、 ブラウザの言語 (`Accept-Language`) の先頭が日本語なら日本語、
それ以外は英語です。

タップした資料は HTML と同じ口で開きます。 ブラウザでは新しいタブ、 iPhone の app では app の中の閲覧の画面、
ホーム画面の PWA では会話の上のプレビューの枠です。 [`page_origin`](config.md) の folder の中の資料は、 その HTML
と同じ origin で開きます。

## 閉じて会話へ戻る

| 開き方 | 戻る口 |
|---|---|
| ブラウザの新しいタブ | そのタブを閉じる (= ブラウザの操作) |
| iPhone の app | 閲覧の画面の ✕ (「完了」) |
| ホーム画面の PWA | プレビューの枠の ✕ (= 枠の中で別の頁へ移った後も、 同じ ✕ で会話へ戻ります) |

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

## Markdown

書いた HTML は通さず、 文字として出します。 見出しには GitHub と同じ作りの `id` が付くので、 `#見出し` のリンクが
効きます。 資料の頁が元の file と同じ path に在るので、 相対のリンクと図は書いたとおりに届きます。 次の 3 つは
頁の側で整えます。

- **図の file が無い (または配れない) 時**は、 壊れた画像ではなく「図が見つかりません: <path>」 (英語では `Image not found: <path>`) の枠を出します
- **目次のリンクの語が見出しと合っていない時** (= 番号や括弧の中を省いた目次) は、 リンクの語が順に含まれる最初の
  見出しへ張り直します。 別の md の見出しへのリンク (`other.md#見出し`) も、 行き先の md の見出しで同じように合わせます。
  語がどの見出しにも含まれない時は、 書いたままにします
- **外の URL の画像**は、 頁が外へ通信できないので読み込まず、 そう分かる枠にします

## 必要な道具

backend を動かす機械に、 次の command が要ります (= 使う種類の分だけ。 無い時は変換の画面にその command の名前が出ます)。

| 種類 | command | 入れ方 (macOS) |
|---|---|---|
| PDF・Office・tif の頁の画像 | `pdftoppm` (poppler) | `brew install poppler` |
| Office | `soffice` (LibreOffice) | `brew install --cask libreoffice` |
| tif | `tiff2pdf` (libtiff。 poppler と一緒に入ります) | `brew install libtiff` |

tif は `tiff2pdf` が無い時、 macOS の `sips` で 1 頁目だけを画像にします。 command は `PATH` に加えて
`/opt/homebrew/bin`・`/usr/local/bin`・`/Applications/LibreOffice.app/Contents/MacOS` も探します (= 常駐の
`PATH` が短くても動きます)。 Markdown の変換には Python の `markdown-it-py` を使います (`backend/requirements.txt`)。

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
