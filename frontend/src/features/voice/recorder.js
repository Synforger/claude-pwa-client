// 人の声を録る (= マイクを開いて、 止めた時に 1 つの音にして返す)。 通信も画面も持たない。
//
// 形式はブラウザに任せる (= Chromium は webm/opus、 Safari は mp4/AAC)。 形式の変換は聞き取りの engine が行う。
// 録り終えたらマイクを閉じる (= 開いたままだと、 ブラウザのマイクの印が点いたままになる)。

const AUDIO = { audio: { echoCancellation: true, noiseSuppression: true } }

function defaultMedia() {
  return {
    open: () => navigator.mediaDevices.getUserMedia(AUDIO),
    Recorder: window.MediaRecorder,
  }
}

// 録り始める。 返す物の stop() は録った音 (= Blob) を、 cancel() は何も返さずにマイクを閉じる。
export async function startRecording(media = defaultMedia()) {
  if (!media.Recorder || !media.open) throw new Error('MediaRecorder is not available')
  const stream = await media.open()
  const close = () => { for (const track of stream.getTracks()) track.stop() }
  let recorder
  try {
    recorder = new media.Recorder(stream)
  } catch (error) {
    close()
    throw error
  }
  const chunks = []
  recorder.ondataavailable = (event) => { if (event.data && event.data.size > 0) chunks.push(event.data) }
  const stopped = new Promise((resolve) => { recorder.onstop = resolve })
  recorder.start()
  let done = false
  const end = async () => {
    if (done) return stopped
    done = true
    if (recorder.state !== 'inactive') recorder.stop()
    await stopped
    close()
    return stopped
  }
  return {
    async stop() {
      await end()
      return new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || 'audio/webm' })
    },
    async cancel() { await end() },
  }
}
