// 声 (= -1〜1 の Float32Array) を、 WAV 形式 (= 16 bit・1 ch の PCM) の Blob にする。 聞き取りの engine へ渡す形。

export function encodeWav(samples, sampleRate) {
  const data = samples.length * 2
  const buffer = new ArrayBuffer(44 + data)
  const view = new DataView(buffer)
  const text = (at, s) => { for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i)) }
  text(0, 'RIFF')
  view.setUint32(4, 36 + data, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)            // fmt の大きさ
  view.setUint16(20, 1, true)             // PCM
  view.setUint16(22, 1, true)             // 1 ch
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 1 秒の大きさ
  view.setUint16(32, 2, true)             // 1 点の大きさ
  view.setUint16(34, 16, true)            // 16 bit
  text(36, 'data')
  view.setUint32(40, data, true)
  for (let i = 0; i < samples.length; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true)
  }
  return new Blob([buffer], { type: 'audio/wav' })
}
