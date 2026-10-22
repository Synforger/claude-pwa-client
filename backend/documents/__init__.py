"""資料 (= pdf・Office・tif) をブラウザで開ける形にする。

- `convert`: pdf・Office・tif を頁ごとの JPEG にする (= 外部の command を shell を通さずに呼ぶ)
- `store`: 変換結果の控え (= 元の file が変わるまで持つ) と、 変換の待ちの状態
- `pages`: 変換結果・待ち・失敗の HTML の頁
"""
