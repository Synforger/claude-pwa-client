// Browser-side drawing for attached images: decode a picture, draw part of it on a canvas, encode the result.
// imageStore.js calls it when an image is saved (a large photo is scaled down, and every image gets a thumbnail).
// The arithmetic is in imageGeometry.js.
import { thumbnailPlan } from './imageGeometry.js'

// The thumbnail's side. A bubble shows an attached image in a 180 × 180 CSS px box (`.msg-image` in MessageItem.css,
// `object-fit: cover`), and an iPhone has 3 device pixels to a CSS pixel: 180 × 3 = 540. Keep it in step with that
// rule; a larger box needs a larger thumbnail.
export const THUMBNAIL_SIDE_PX = 540

const ENCODE_QUALITY = 0.85

/** What a resized copy of `file` is encoded as: PNG stays PNG (it may have transparency), anything else is JPEG. */
export function outputType(file) {
  return file.type === 'image/png' ? 'image/png' : 'image/jpeg'
}

/** Decodes an image into a bitmap, or returns null when the browser cannot (or has no `createImageBitmap`). */
export async function decodeBitmap(blob) {
  if (typeof createImageBitmap === 'undefined') return null
  try {
    return await createImageBitmap(blob)
  } catch {
    return null
  }
}

/**
 * Draws `source` ({ x, y, width, height }, a rectangle of the bitmap) onto a canvas of `outputWidth` × `outputHeight`
 * and encodes it as `type`. Resolves to null when the canvas cannot encode it.
 */
export function drawToBlob(bitmap, source, outputWidth, outputHeight, type) {
  const canvas = document.createElement('canvas')
  canvas.width = outputWidth
  canvas.height = outputHeight
  canvas.getContext('2d').drawImage(bitmap, source.x, source.y, source.width, source.height, 0, 0, outputWidth, outputHeight)
  return new Promise((resolve) => canvas.toBlob(resolve, type, ENCODE_QUALITY))
}

/**
 * The thumbnail of an image (see `thumbnailPlan`), or null when the image is already as small as its thumbnail would
 * be or cannot be decoded here; the caller then shows the original.
 */
export async function makeThumbnail(blob) {
  if (typeof document === 'undefined') return null
  const bitmap = await decodeBitmap(blob)
  if (!bitmap) return null
  try {
    const plan = thumbnailPlan(bitmap.width, bitmap.height, THUMBNAIL_SIDE_PX)
    if (!plan) return null
    const source = { x: plan.sourceX, y: plan.sourceY, width: plan.sourceSide, height: plan.sourceSide }
    return await drawToBlob(bitmap, source, plan.outputSide, plan.outputSide, outputType(blob))
  } catch {
    return null
  } finally {
    if (bitmap.close) bitmap.close()
  }
}
