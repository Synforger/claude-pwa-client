// 小窓の吹き出しを Mac で絵にする (= iPhone の app と同じ ChatMarkdown.swift を使う)。
//
//   swift の build: tools/pip-preview/build.sh
//   使い方: pip-preview <出力の folder> <markdown の file>...
//
// file ごとに、 返事の吹き出し 1 つを、 小窓と同じ幅・字の大きさ・色で PNG にする (= 2 倍の解像度)。
import AppKit

let arguments = CommandLine.arguments.dropFirst()
guard arguments.count >= 2, let outDir = arguments.first else {
    FileHandle.standardError.write("usage: pip-preview <out-dir> <markdown-file>...\n".data(using: .utf8)!)
    exit(2)
}
try FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

for path in arguments.dropFirst() {
    let markdown = try String(contentsOfFile: path, encoding: .utf8)
    let mine = path.contains(".user.")
    let (content, bubble) = PictureBubble.layout(markdown, mine: mine)
    let size = CGSize(width: PictureBubble.canvas.width, height: bubble.height + PictureBubble.margin * 2)
    let scale: CGFloat = 2
    let context = CGContext(
        data: nil, width: Int(size.width * scale), height: Int(size.height * scale), bitsPerComponent: 8, bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    // 上が原点 (= UIKit と同じ向き) にして描く
    context.translateBy(x: 0, y: size.height * scale)
    context.scaleBy(x: scale, y: -scale)
    NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
    context.setFillColor(PictureBubble.background.cgColor)
    context.fill(CGRect(origin: .zero, size: size))
    let x = mine ? size.width - PictureBubble.margin - bubble.width : PictureBubble.margin
    let frame = CGRect(x: x, y: PictureBubble.margin, width: bubble.width, height: bubble.height)
    context.setFillColor((mine ? PictureBubble.mineColor : PictureBubble.theirsColor).cgColor)
    context.addPath(CGPath(roundedRect: frame, cornerWidth: 12, cornerHeight: 12, transform: nil))
    context.fillPath()
    content.draw(at: CGPoint(x: frame.minX + PictureBubble.padding.width, y: frame.minY + PictureBubble.padding.height),
                 in: context)
    let image = context.makeImage()!
    let name = (path as NSString).lastPathComponent.replacingOccurrences(of: ".md", with: ".png")
    let out = (outDir as NSString).appendingPathComponent(name)
    let rep = NSBitmapImageRep(cgImage: image)
    try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
    print(out)
}
