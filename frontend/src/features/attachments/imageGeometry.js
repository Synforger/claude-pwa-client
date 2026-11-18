// Sizes for the pictures an attached image is drawn as: plain arithmetic, no browser objects, so a test can call it
// directly. imageResize.js draws with these numbers and imageStore.js decides from them whether a thumbnail is worth
// keeping.

/** The scale that makes the long side of a `width` × `height` image fit `maxDimension`; 1 when it already fits. */
export function fitScale(width, height, maxDimension) {
  return Math.min(1, maxDimension / Math.max(width, height))
}

/**
 * The thumbnail of an image that a square box shows with `object-fit: cover`: the centred square of the image, drawn
 * `outputSide` px wide. The box shows only that square, so the thumbnail looks the same as the original there.
 * `outputSide` is never larger than the square itself (nothing is enlarged), and it is `maxSide` at most.
 *
 * Returns null when the thumbnail would not be smaller than the image (a square image no larger than `maxSide`), so
 * the caller keeps showing the original.
 */
export function thumbnailPlan(width, height, maxSide) {
  const sourceSide = Math.min(width, height)
  const outputSide = Math.min(sourceSide, maxSide)
  if (width * height <= outputSide * outputSide) return null
  return {
    sourceX: Math.floor((width - sourceSide) / 2),
    sourceY: Math.floor((height - sourceSide) / 2),
    sourceSide,
    outputSide,
  }
}
