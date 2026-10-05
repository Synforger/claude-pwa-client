// Minimal PNG writer for fixtures: an 8-bit RGB image from a per-pixel function,
// so a scenario can make an image of any size without a binary file in the repo.
import { deflateSync } from 'node:zlib'

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return table
})()

function crc32(buf) {
  let c = 0xffffffff
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
  const head = Buffer.alloc(8)
  head.writeUInt32BE(data.length, 0)
  head.write(type, 4, 'ascii')
  const tail = Buffer.alloc(4)
  tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0)
  return Buffer.concat([head, data, tail])
}

// pixel(x, y) -> [r, g, b]
export function makePng(width, height, pixel) {
  const stride = width * 3 + 1
  const raw = Buffer.alloc(stride * height)
  for (let y = 0; y < height; y++) {
    const row = y * stride
    raw[row] = 0 // filter: none
    for (let x = 0; x < width; x++) {
      const [r, g, b] = pixel(x, y)
      const at = row + 1 + x * 3
      raw[at] = r
      raw[at + 1] = g
      raw[at + 2] = b
    }
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 2 // colour type: RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

// A test card: a 100px grid over a gradient, with a distinct colour block in each
// corner (red top-left, green top-right, blue bottom-left, yellow bottom-right),
// so a screenshot shows which part of the image is in view and at what scale.
export function testCard(width, height) {
  const corner = Math.max(1, Math.round(Math.min(width, height) / 8))
  return makePng(width, height, (x, y) => {
    const left = x < corner
    const right = x >= width - corner
    const top = y < corner
    const bottom = y >= height - corner
    if (top && left) return [220, 40, 40]
    if (top && right) return [40, 180, 70]
    if (bottom && left) return [50, 90, 220]
    if (bottom && right) return [235, 200, 40]
    if (x % 100 === 0 || y % 100 === 0) return [20, 20, 20]
    return [Math.round(60 + 160 * (x / width)), Math.round(60 + 160 * (y / height)), 150]
  })
}
