// 会話 (= 声で話す) の画面が使う部品を、 npm の package から build の出力へ写す。
//
// 部品は 4 つ: 声の区間を見つける model と、 その音を受ける処理 (= @ricky0123/vad-web)、 model を動かす本体
// (= onnxruntime-web の wasm と、 それを読む mjs)。 画面は実行中にこれらを URL で読む (= import で bundle に
// 入る物ではない) ので、 vite の素通しでは出力に載らない。 onnxruntime-web は、 本体を外の置き場から読む版
// (= 条件 `onnxruntime-web-use-extern-wasm`、 vite.config.js) を使う (= 本体を bundle の側でも出力しない)。
//
// 置き場は `assets/voice-<中身の hash>/`。 `/assets/` は「中身が変わらない」 前提で長く cache される
// (= backend/_internal/static_files.py と sw.js) ので、 部品の版が変われば置き場の名前も変わる形にする。
// 画面は置き場を `__VOICE_ASSET_BASE__` で知る。
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const FILES = [
  ['@ricky0123/vad-web/dist/vad.worklet.bundle.min.js', 'text/javascript'],
  ['@ricky0123/vad-web/dist/silero_vad_v5.onnx', 'application/octet-stream'],
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.wasm', 'application/wasm'],
  ['onnxruntime-web/dist/ort-wasm-simd-threaded.mjs', 'text/javascript'],
]

// 写す file の一覧と、 置き場の名前 (= 先頭の / は付けない)。
export function voiceAssets(modulesDir = resolve(import.meta.dirname, '..', 'node_modules')) {
  const hash = createHash('sha256')
  const files = FILES.map(([from, type]) => {
    const path = resolve(modulesDir, from)
    const source = readFileSync(path)
    hash.update(from).update(source)
    return { name: from.split('/').pop(), path, type, source }
  })
  return { dir: `assets/voice-${hash.digest('hex').slice(0, 12)}/`, files }
}

export function voiceAssetsPlugin() {
  const { dir, files } = voiceAssets()
  return {
    name: 'voice-assets',
    config: () => ({ define: { __VOICE_ASSET_BASE__: JSON.stringify(`/${dir}`) } }),
    // 開発用の server (= vite) では、 同じ URL で node_modules の中身を返す。
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const file = files.find((f) => req.url === `/${dir}${f.name}`)
        if (!file) return next()
        res.setHeader('Content-Type', file.type)
        res.end(file.source)
      })
    },
    generateBundle() {
      for (const file of files) this.emitFile({ type: 'asset', fileName: `${dir}${file.name}`, source: file.source })
    },
  }
}
