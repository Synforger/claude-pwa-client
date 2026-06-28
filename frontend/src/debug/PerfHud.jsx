// ADR-012 PerfHud: 自身の render 回数 / FPS / メモリを表示する簡易 HUD。
// 個別 component の re-render 原因は React DevTools Profiler が王道だが、 軽量 HUD として開発者
// が「全体的に重い瞬間」 を即視できる目的で常駐表示。

import { useEffect, useState } from 'react'

export default function PerfHud() {
  const [fps, setFps] = useState(0)
  const [mem, setMem] = useState(null)

  useEffect(() => {
    let frames = 0
    let lastTs = performance.now()
    let raf = 0
    function tick(ts) {
      frames += 1
      if (ts - lastTs >= 1000) {
        setFps(Math.round((frames * 1000) / (ts - lastTs)))
        frames = 0
        lastTs = ts
        const perfMem = performance.memory
        if (perfMem && typeof perfMem.usedJSHeapSize === 'number') {
          setMem(Math.round(perfMem.usedJSHeapSize / 1024 / 1024))
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <section style={{ padding: 8, fontFamily: 'monospace', fontSize: 12 }}>
      <h3 style={{ margin: '0 0 8px' }}>PerfHud</h3>
      <div>FPS: <strong>{fps}</strong></div>
      <div>JS heap used: {mem !== null ? `${mem} MB` : 'unavailable (= Chromium only)'}</div>
    </section>
  )
}
