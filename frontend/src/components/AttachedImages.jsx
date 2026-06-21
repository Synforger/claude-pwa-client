import { memo, useEffect, useState } from 'react'
import { getImageURL } from '../utils/imageStore.js'
import './AttachedImages.css'

// user メッセージの画像表示。 imageRefs (= IndexedDB の ID 配列) から URL を取り出し、
// 表示中だけ ObjectURL を保持してアンマウント時に revoke する。
// 後方互換: legacy data URL `imageUrls` も併せて受ける。
// memo: 親 (MessageItem) は memo 済だが、 親の親 (Messages list / App) の何かが変わった時に
// props 同一でも再 render が走り、 IndexedDB fetch + ObjectURL 再作成のループが起きる。
// 添付画像があるメッセージで入力中にカクつく原因の一つだったので props 比較で間引く。
function AttachedImagesImpl({ imageRefs, imageUrls }) {
  const [refUrls, setRefUrls] = useState(() => imageRefs?.map(() => null) || [])

  useEffect(() => {
    if (!imageRefs || imageRefs.length === 0) return
    let cancelled = false
    const created = []
    Promise.all(imageRefs.map(id => getImageURL(id).catch(() => null)))
      .then(urls => {
        if (cancelled) {
          urls.forEach(u => u && URL.revokeObjectURL(u))
          return
        }
        urls.forEach(u => { if (u) created.push(u) })
        setRefUrls(urls)
      })
    return () => {
      cancelled = true
      created.forEach(u => URL.revokeObjectURL(u))
    }
  }, [imageRefs])

  // imageRefs (= IndexedDB key) が有る message は **そちらを真値**にする (= 一度
  // 永続化された画像は ObjectURL 失効後も復元可)。 imageRefs が空 / 未定義の
  // 旧 message だけ imageUrls フォールバックを使う。 両者を merge して並べる旧実装は
  // リロード後に「失効 URL = ?表示」 と「IndexedDB 復元 URL = 正常表示」 が
  // 並列に出て二重 + 片方が ? になる原因だった。
  // F-53: IndexedDB から URL を作る間 (= 最初の数フレーム) は refUrls が全部 null になり
  // 旧実装は何も描画しなかった。 添付枚数分の placeholder skeleton を即出して、 fetch
  // 完了で skeleton が消え画像が現れる体験にする (= 初回 render での「何も無い」 を消す)。
  const hasRefs = imageRefs && imageRefs.length > 0
  if (hasRefs) {
    return (
      <div className="attach-images">
        {refUrls.map((url, j) => (
          url
            ? <img key={j} src={url} className="msg-image" alt="" />
            : <div
                key={j}
                className="msg-image"
                // skeleton スタイルは inline で持つ (= MessageItem.css は W2-B スコープなので
                // 衝突回避。 IndexedDB load 完了で img に差し替わる短時間だけ表示される)。
                style={{
                  background: 'linear-gradient(90deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.10) 50%, rgba(255,255,255,0.04) 100%)',
                  backgroundSize: '200% 100%',
                  animation: 'cpc-img-skeleton 1.2s linear infinite',
                  minWidth: 80,
                  minHeight: 80,
                }}
                aria-hidden="true"
              />
        ))}
      </div>
    )
  }
  const allUrls = imageUrls || []
  if (allUrls.length === 0) return null
  return (
    <div className="attach-images">
      {allUrls.map((url, j) => (
        <img key={j} src={url} className="msg-image" alt="" />
      ))}
    </div>
  )
}

// imageRefs / imageUrls は配列なので参照同一で比較したい。 親で同じ配列を渡し続けてる
// ケースがほとんどなので shallow で十分。 中身が増減した時のみ再 fetch する。
export default memo(AttachedImagesImpl, (prev, next) => (
  prev.imageRefs === next.imageRefs && prev.imageUrls === next.imageUrls
))
