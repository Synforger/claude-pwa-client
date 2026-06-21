# overlays/

frontend で「全画面/全幅を覆う一時 UI」 だけを置く。 普段は閉じていて、
ユーザ操作 (= タップ / ショートカット / lazy 起動) で開閉する画面を指す。
すべて App.jsx 側で `lazy(() => import(...))` + `<Suspense fallback={null}>`
配下に置かれ、 初回 paint には乗らない (= 初回 bundle 削減 + 開いた時だけ
chunk を取りに行く)。

## ここに置くべきもの

- modal / dialog (= 中央 or 全画面ポップアップ、 ESC や outside-click で閉じる)
- drawer (= サイドからスライドインするパネル)
- 全画面プレビュー (= ファイル / 画像 / log 等を本文と切り離して見るビュー)
- popover / quick picker (= 軽量だが本文に被さるピッカー UI)

## ここに置かないもの

- 常時 mount される本文の構成要素 (= ChatInput / StatusBar / ActivityBar 等は
  `components/` 直下)
- 埋め込み iframe など、 表示位置は固定だが「覆いかぶさらない」 UI (=
  MoonlightFrame は components/ 側)
- 純データ helper / hooks (= utils/ や hooks/ へ)

## 命名と配線

- file 名は `<Name>.jsx` + `<Name>.css` 同居 (= Modal.css は overlays 全体の
  共通枠で複数 file が import する)
- App.jsx 側に `lazy(() => import('./overlays/<Name>.jsx'))` を 1 行足し、
  `<Suspense fallback={null}>` 配下にレンダする
- ESC ハンドリングは `hooks/useEscape.js`、 outside-click は
  `hooks/useOutsideClick.js` を使う (= 各 overlay が同じ仕組みに揃う)
