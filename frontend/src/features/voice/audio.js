// 音を鳴らす所 (= ブラウザの AudioContext)。
//
// ブラウザは、 人が画面を押した後でないと音を鳴らさせない。 unlockAudio() を、 ボタンを押した handler の
// 中で 1 度呼んでおくと、 以後は押さなくても鳴らせる。

let context = null

export function unlockAudio() {
  const Ctor = globalThis.AudioContext || globalThis.webkitAudioContext
  if (!Ctor) throw new Error('AudioContext is not available')
  if (!context) context = new Ctor()
  if (context.state !== 'running') context.resume().catch(() => { /* 鳴らす時にもう 1 度試す */ })
}

// 音 (= WAV などの中身) を鳴らす。 done は鳴り終えた時か止められた時に済み、 鳴らせなければ失敗する。
export function playSound(data) {
  let source = null
  let stopped = false
  const done = (async () => {
    if (!context) throw new Error('audio is locked until the voice button is pressed')
    if (context.state !== 'running') await context.resume()
    const buffer = await context.decodeAudioData(data)
    if (stopped) return
    await new Promise((resolve) => {
      source = context.createBufferSource()
      source.buffer = buffer
      source.connect(context.destination)
      source.onended = resolve
      source.start()
    })
  })()
  return {
    done,
    stop() {
      stopped = true
      try { source?.stop() } catch { /* まだ鳴り始めていない */ }
    },
  }
}
