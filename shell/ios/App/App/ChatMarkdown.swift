import CoreGraphics
import Foundation
#if canImport(UIKit)
import UIKit
typealias MarkdownFont = UIFont
typealias MarkdownColor = UIColor
#else
import AppKit
typealias MarkdownFont = NSFont
typealias MarkdownColor = NSColor
#endif

/// 小窓の吹き出しの中身: markdown を、 決めた幅に収まる絵に組む (= 画面のメモと同じく、 表・見出し・箇条書き・
/// 引用・コードの枠・区切りの線まで描く)。
///
/// 読み取りは Foundation の markdown (= `AttributedString(markdown:)` の `.full`。 表は GitHub の書き方) に任せ、
/// 返ってくる段落ごとの印 (= `presentationIntent`) から、 段落・表・コードの枠を組み立てる。 小窓は app が裏に回って
/// いる間に描くので、 画面 (= WKWebView) の描画は使えない。
///
/// iPhone の app と Mac の確かめの道具 (= `shell/ios/tools/pip-preview`) の両方で build する (= 同じ code の絵を
/// Mac で出して確かめる)。 描く先は、 上が原点の CGContext (= UIKit の描画の向き)。
struct ChatMarkdown {
    struct Style {
        var font: MarkdownFont
        var color: MarkdownColor
        /// 引用・表の線・コードの枠の地
        var dim: MarkdownColor
        var line: MarkdownColor
        var codeBackground: MarkdownColor
    }

    /// 組み上がった絵の大きさ (= 描く幅は、 中身が使う分だけ。 最大は init の width)
    let size: CGSize
    private let blocks: [Laid]

    /// 段落の間
    static let blockGap: CGFloat = 6
    /// 箇条書きの 1 段の字下げ
    static let listIndent: CGFloat = 14
    /// 表のマスの内側の余白
    static let cellPadding = CGSize(width: 5, height: 3)
    /// コードの枠の内側の余白
    static let codePadding: CGFloat = 5
    /// 表とコードを縮める下限 (= 元の字の大きさに対する割合)。 これでも入らない表はマスの中で折り返し、 コードは右で切る
    static let smallestScale: CGFloat = 0.6

    init(markdown: String, width: CGFloat, style: Style) {
        let parts = Self.parse(markdown, style: style)
        var laid: [Laid] = []
        var y: CGFloat = 0
        var used: CGFloat = 0
        for part in parts {
            let block = Self.lay(part, width: width, style: style, top: y)
            laid.append(block)
            y = block.frame.maxY + Self.blockGap
            used = max(used, block.frame.maxX)
        }
        blocks = laid
        size = CGSize(width: ceil(min(width, used)), height: ceil(max(0, y - Self.blockGap)))
    }

    /// origin を左上にして描く。
    func draw(at origin: CGPoint, in context: CGContext) {
        for block in blocks {
            block.draw(origin, context)
        }
    }

    // MARK: - 読み取り

    private enum Part {
        case text(NSAttributedString, indent: CGFloat, quote: Bool)
        case code(String)
        case table(rows: [[NSAttributedString]], header: Int, alignments: [NSTextAlignment])
        case rule
    }

    private static func parse(_ markdown: String, style: Style) -> [Part] {
        let options = AttributedString.MarkdownParsingOptions(
            allowsExtendedAttributes: false, interpretedSyntax: .full, failurePolicy: .returnPartiallyParsedIfPossible)
        guard let parsed = try? AttributedString(markdown: markdown, options: options) else {
            return [.text(NSAttributedString(string: markdown, attributes: textAttributes(style.font, style.color)),
                          indent: 0, quote: false)]
        }
        var parts: [Part] = []
        var paragraph: (id: Int, text: NSMutableAttributedString, indent: CGFloat, quote: Bool)?
        var table: (id: Int, rows: [[NSMutableAttributedString]], header: Int, alignments: [NSTextAlignment],
                    row: Int, cell: Int)?
        var code: (id: Int, text: String)?
        var listItems = Set<Int>()   // 頭の印を付け終えた箇条

        func flushParagraph() {
            if let p = paragraph { parts.append(.text(p.text, indent: p.indent, quote: p.quote)) }
            paragraph = nil
        }
        func flushTable() {
            if let t = table { parts.append(.table(rows: t.rows, header: t.header, alignments: t.alignments)) }
            table = nil
        }
        func flushCode() {
            if let c = code { parts.append(.code(c.text.hasSuffix("\n") ? String(c.text.dropLast()) : c.text)) }
            code = nil
        }

        for run in parsed.runs {
            let text = String(parsed[run.range].characters)
            let components = run.presentationIntent?.components ?? []
            let inline = run.inlinePresentationIntent ?? []

            if let tableIntent = components.first(where: { if case .table = $0.kind { return true } else { return false } }) {
                flushParagraph(); flushCode()
                if table?.id != tableIntent.identity {
                    flushTable()
                    var alignments: [NSTextAlignment] = []
                    if case let .table(columns) = tableIntent.kind {
                        alignments = columns.map { column in
                            switch column.alignment {
                            case .right: return .right
                            case .center: return .center
                            default: return .left
                            }
                        }
                    }
                    table = (tableIntent.identity, [], 0, alignments, -1, -1)
                }
                var rowId = -1, column = 0, isHeader = false
                for component in components {
                    switch component.kind {
                    case let .tableCell(index): column = index
                    case .tableHeaderRow: rowId = component.identity; isHeader = true
                    case .tableRow: rowId = component.identity
                    default: break
                    }
                }
                if table!.row != rowId {
                    table!.rows.append([])
                    table!.row = rowId
                    if isHeader { table!.header = 1 }
                }
                while table!.rows[table!.rows.count - 1].count <= column {
                    table!.rows[table!.rows.count - 1].append(NSMutableAttributedString())
                }
                let font = isHeader ? bold(style.font) : style.font
                table!.rows[table!.rows.count - 1][column].append(styledRun(text, inline: inline, font: font, style: style))
                continue
            }
            flushTable()

            guard let block = components.first else {
                flushParagraph(); flushCode()
                parts.append(.text(styledRun(text, inline: inline, font: style.font, style: style), indent: 0, quote: false))
                continue
            }
            switch block.kind {
            case .codeBlock:
                flushParagraph()
                if code?.id != block.identity { flushCode(); code = (block.identity, "") }
                code!.text += text
                continue
            case .thematicBreak:
                flushParagraph(); flushCode()
                parts.append(.rule)
                continue
            default:
                flushCode()
            }

            if paragraph?.id != block.identity {
                flushParagraph()
                let depth = components.filter { if case .listItem = $0.kind { return true } else { return false } }.count
                let quote = components.contains { if case .blockQuote = $0.kind { return true } else { return false } }
                var font = style.font
                if case let .header(level) = block.kind {
                    font = bold(style.font, scale: [1.3, 1.2, 1.1][min(max(level, 1), 3) - 1])
                }
                let started = NSMutableAttributedString()
                // 箇条の最初の段落にだけ頭の印を付ける (= 中黒、 番号付きなら番号)
                if let item = components.first(where: { if case .listItem = $0.kind { return true } else { return false } }),
                   !listItems.contains(item.identity) {
                    listItems.insert(item.identity)
                    var marker = "•"
                    if case let .listItem(ordinal) = item.kind,
                       let list = components.first(where: { $0.identity != item.identity && isList($0) }),
                       case .orderedList = list.kind {
                        marker = "\(ordinal)."
                    }
                    started.append(NSAttributedString(string: marker + " ", attributes: textAttributes(font, style.color)))
                }
                let indent = CGFloat(max(0, depth - 1)) * listIndent
                paragraph = (block.identity, started, indent, quote)
                paragraph!.text.addAttribute(.paragraphStyle, value: hanging(indent: indent, marker: started),
                                             range: NSRange(location: 0, length: started.length))
            }
            let font: MarkdownFont
            if case let .header(level) = block.kind {
                font = bold(style.font, scale: [1.3, 1.2, 1.1][min(max(level, 1), 3) - 1])
            } else {
                font = style.font
            }
            let piece = styledRun(text, inline: inline, font: font, style: style, dim: paragraph!.quote)
            paragraph!.text.append(piece)
        }
        flushParagraph(); flushTable(); flushCode()
        // 段落の字下げ (= 頭の印の後ろで折り返した行をそろえる) を全体に広げる
        return parts.map { part in
            guard case let .text(text, indent, quote) = part, text.length > 0 else { return part }
            let whole = NSMutableAttributedString(attributedString: text)
            let style = text.attribute(.paragraphStyle, at: 0, effectiveRange: nil) ?? hanging(indent: indent, marker: nil)
            whole.addAttribute(.paragraphStyle, value: style, range: NSRange(location: 0, length: whole.length))
            return .text(whole, indent: indent, quote: quote)
        }
    }

    private static func isList(_ component: PresentationIntent.IntentType) -> Bool {
        switch component.kind {
        case .orderedList, .unorderedList: return true
        default: return false
        }
    }

    private static func hanging(indent: CGFloat, marker: NSAttributedString?) -> NSParagraphStyle {
        let style = NSMutableParagraphStyle()
        style.firstLineHeadIndent = indent
        style.headIndent = indent + ceil(marker?.size().width ?? 0)
        style.lineBreakMode = .byWordWrapping
        return style
    }

    private static func textAttributes(_ font: MarkdownFont, _ color: MarkdownColor) -> [NSAttributedString.Key: Any] {
        [.font: font, .foregroundColor: color]
    }

    private static func styledRun(
        _ text: String, inline: InlinePresentationIntent, font base: MarkdownFont, style: Style, dim: Bool = false
    ) -> NSAttributedString {
        var font = base
        if inline.contains(.code) {
            font = monospaced(size: base.pointSize - 1)
        }
        if inline.contains(.stronglyEmphasized) { font = bold(font) }
        if inline.contains(.emphasized) { font = italic(font) }
        var attributes = textAttributes(font, dim ? style.dim : style.color)
        if inline.contains(.strikethrough) { attributes[.strikethroughStyle] = NSUnderlineStyle.single.rawValue }
        return NSAttributedString(string: text, attributes: attributes)
    }

    // MARK: - 字の形 (= iPhone と Mac で名前が違う所)

    static func monospaced(size: CGFloat) -> MarkdownFont {
        MarkdownFont.monospacedSystemFont(ofSize: size, weight: .regular)
    }

    static func bold(_ font: MarkdownFont, scale: CGFloat = 1) -> MarkdownFont {
        #if canImport(UIKit)
        let descriptor = font.fontDescriptor.withSymbolicTraits(.traitBold) ?? font.fontDescriptor
        return MarkdownFont(descriptor: descriptor, size: font.pointSize * scale)
        #else
        let descriptor = font.fontDescriptor.withSymbolicTraits(.bold)
        return MarkdownFont(descriptor: descriptor, size: font.pointSize * scale) ?? font
        #endif
    }

    static func italic(_ font: MarkdownFont) -> MarkdownFont {
        #if canImport(UIKit)
        let descriptor = font.fontDescriptor.withSymbolicTraits(.traitItalic) ?? font.fontDescriptor
        return MarkdownFont(descriptor: descriptor, size: font.pointSize)
        #else
        let descriptor = font.fontDescriptor.withSymbolicTraits(.italic)
        return MarkdownFont(descriptor: descriptor, size: font.pointSize) ?? font
        #endif
    }

    static func resized(_ font: MarkdownFont, to size: CGFloat) -> MarkdownFont {
        #if canImport(UIKit)
        return font.withSize(size)
        #else
        return MarkdownFont(descriptor: font.fontDescriptor, size: size) ?? font
        #endif
    }

    // MARK: - 組み立て

    /// 組み上がった 1 段 (= 吹き出しの中の位置と、 描き方)
    private struct Laid {
        let frame: CGRect
        let draw: (CGPoint, CGContext) -> Void
    }

    private static func lay(_ part: Part, width: CGFloat, style: Style, top: CGFloat) -> Laid {
        switch part {
        case let .text(text, _, quote):
            let bar: CGFloat = quote ? 8 : 0
            let box = measure(text, width: width - bar)
            let frame = CGRect(x: 0, y: top, width: box.width + bar, height: box.height)
            return Laid(frame: frame) { origin, context in
                if quote {
                    context.setFillColor(style.line.cgColor)
                    context.fill(CGRect(x: origin.x, y: origin.y + frame.minY, width: 3, height: frame.height))
                }
                draw(text, in: CGRect(x: origin.x + bar, y: origin.y + frame.minY, width: width - bar, height: box.height))
            }

        case .rule:
            let frame = CGRect(x: 0, y: top, width: width, height: 5)
            return Laid(frame: frame) { origin, context in
                context.setFillColor(style.line.cgColor)
                context.fill(CGRect(x: origin.x, y: origin.y + frame.minY + 2, width: width, height: 1))
            }

        case let .code(source):
            // 行を折り返さない (= ツリーや字下げの位置を崩さない)。 幅の揃った字で、 入らなければ縮め、 それでも入らない
            // 行は右で切る
            let lines = source.components(separatedBy: "\n")
            let inner = width - codePadding * 2
            var font = monospaced(size: style.font.pointSize - 2)
            let widest = lines.map { NSAttributedString(string: $0, attributes: textAttributes(font, style.color)).size().width }
                .max() ?? 0
            if widest > inner {
                font = monospaced(size: max(font.pointSize * smallestScale, font.pointSize * inner / widest))
            }
            let rendered = lines.map { NSAttributedString(string: $0, attributes: textAttributes(font, style.color)) }
            let lineHeight = ceil(font.ascender - font.descender + font.leading)
            let used = min(inner, ceil(rendered.map { $0.size().width }.max() ?? 0))
            let frame = CGRect(x: 0, y: top, width: used + codePadding * 2,
                               height: CGFloat(lines.count) * lineHeight + codePadding * 2)
            return Laid(frame: frame) { origin, context in
                let box = frame.offsetBy(dx: origin.x, dy: origin.y)
                context.setFillColor(style.codeBackground.cgColor)
                context.addPath(CGPath(roundedRect: box, cornerWidth: 6, cornerHeight: 6, transform: nil))
                context.fillPath()
                context.saveGState()
                context.clip(to: box.insetBy(dx: codePadding, dy: 0))
                for (i, line) in rendered.enumerated() {
                    line.draw(at: CGPoint(x: box.minX + codePadding, y: box.minY + codePadding + CGFloat(i) * lineHeight))
                }
                context.restoreGState()
            }

        case let .table(rows, header, alignments):
            return layTable(rows: rows, header: header, alignments: alignments, width: width, style: style, top: top)
        }
    }

    private static func layTable(
        rows: [[NSAttributedString]], header: Int, alignments: [NSTextAlignment], width: CGFloat, style: Style, top: CGFloat
    ) -> Laid {
        let columns = rows.map(\.count).max() ?? 0
        let pad = cellPadding.width * 2
        // 字を元の大きさで並べた時の列の幅。 入らなければ下限まで縮め、 それでも入らなければ列の幅を割って折り返す
        func natural(_ cells: [[NSAttributedString]]) -> [CGFloat] {
            (0..<columns).map { c in cells.map { c < $0.count ? ceil($0[c].size().width) : 0 }.max() ?? 0 }
        }
        var cells = rows
        var widths = natural(cells)
        let total = widths.reduce(0, +) + pad * CGFloat(columns)
        if total > width, total > 0 {
            let scale = max(smallestScale, (width - pad * CGFloat(columns)) / max(1, total - pad * CGFloat(columns)))
            cells = rows.map { row in row.map { scaled($0, by: scale) } }
            widths = natural(cells)
        }
        let room = width - pad * CGFloat(columns)
        if widths.reduce(0, +) > room {
            // 狭い列は元の幅のまま残し、 余りを広い列で分ける
            let fair = room / CGFloat(max(1, columns))
            let narrow = widths.filter { $0 <= fair }.reduce(0, +)
            let wide = widths.filter { $0 > fair }.reduce(0, +)
            widths = widths.map { $0 <= fair ? $0 : floor($0 / max(1, wide) * (room - narrow)) }
        }
        let aligned = cells.map { row in
            row.enumerated().map { c, cell -> NSAttributedString in
                let text = NSMutableAttributedString(attributedString: cell)
                let paragraph = NSMutableParagraphStyle()
                paragraph.alignment = c < alignments.count ? alignments[c] : .left
                paragraph.lineBreakMode = .byWordWrapping
                text.addAttribute(.paragraphStyle, value: paragraph, range: NSRange(location: 0, length: text.length))
                return text
            }
        }
        let heights = aligned.map { row in
            (row.enumerated().map { c, cell in measure(cell, width: widths[c]).height }.max() ?? 0) + cellPadding.height * 2
        }
        let tableWidth = widths.reduce(0, +) + pad * CGFloat(columns)
        let frame = CGRect(x: 0, y: top, width: tableWidth, height: heights.reduce(0, +))
        return Laid(frame: frame) { origin, context in
            let box = frame.offsetBy(dx: origin.x, dy: origin.y)
            if header > 0, let first = heights.first {
                context.setFillColor(style.codeBackground.cgColor)
                context.fill(CGRect(x: box.minX, y: box.minY, width: box.width, height: first))
            }
            var y = box.minY
            for (r, row) in aligned.enumerated() {
                var x = box.minX
                for (c, cell) in row.enumerated() {
                    draw(cell, in: CGRect(x: x + cellPadding.width, y: y + cellPadding.height,
                                          width: widths[c], height: heights[r] - cellPadding.height * 2))
                    x += widths[c] + pad
                }
                y += heights[r]
            }
            // 枠の線: 外枠と、 行・列の境目
            context.setStrokeColor(style.line.cgColor)
            context.setLineWidth(1)
            context.stroke(box.insetBy(dx: 0.5, dy: 0.5))
            var lineY = box.minY
            for h in heights.dropLast() {
                lineY += h
                context.move(to: CGPoint(x: box.minX, y: lineY)); context.addLine(to: CGPoint(x: box.maxX, y: lineY))
            }
            var lineX = box.minX
            for w in widths.dropLast() {
                lineX += w + pad
                context.move(to: CGPoint(x: lineX, y: box.minY)); context.addLine(to: CGPoint(x: lineX, y: box.maxY))
            }
            context.strokePath()
        }
    }

    private static func scaled(_ text: NSAttributedString, by scale: CGFloat) -> NSAttributedString {
        let copy = NSMutableAttributedString(attributedString: text)
        copy.enumerateAttribute(.font, in: NSRange(location: 0, length: copy.length)) { value, range, _ in
            if let font = value as? MarkdownFont {
                copy.addAttribute(.font, value: resized(font, to: font.pointSize * scale), range: range)
            }
        }
        return copy
    }

    private static func measure(_ text: NSAttributedString, width: CGFloat) -> CGSize {
        let bounds = text.boundingRect(
            with: CGSize(width: max(1, width), height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
        return CGSize(width: ceil(bounds.width), height: ceil(bounds.height))
    }

    private static func draw(_ text: NSAttributedString, in rect: CGRect) {
        text.draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
    }
}

/// 小窓の吹き出しの寸法と色 (= 小窓の `CallPicture` と、 Mac の確かめの道具が同じ値を読む)。
enum PictureBubble {
    /// 描く大きさ (pt)。 小窓は iOS がこの縦横比のまま縮めて出す
    static let canvas = CGSize(width: 300, height: 400)
    static let margin: CGFloat = 10
    static let gap: CGFloat = 8
    static let padding = CGSize(width: 10, height: 7)
    static let fontSize: CGFloat = 20
    static let background = MarkdownColor(white: 0.07, alpha: 1)
    static let mineColor = MarkdownColor(red: 0.18, green: 0.44, blue: 0.84, alpha: 1)
    static let theirsColor = MarkdownColor(white: 0.17, alpha: 1)

    /// 吹き出しの中身の最大の幅 (= 人の発話は右寄せの 85%、 返事は表やコードが入るので窓の幅いっぱい)
    static func contentWidth(mine: Bool) -> CGFloat {
        (canvas.width - margin * 2) * (mine ? 0.85 : 1) - padding.width * 2
    }

    static func style(mine: Bool) -> ChatMarkdown.Style {
        ChatMarkdown.Style(
            font: MarkdownFont.systemFont(ofSize: fontSize),
            color: mine ? MarkdownColor.white : MarkdownColor(white: 0.93, alpha: 1),
            dim: MarkdownColor(white: mine ? 0.85 : 0.7, alpha: 1),
            line: MarkdownColor(white: mine ? 0.8 : 0.45, alpha: 1),
            codeBackground: MarkdownColor(white: mine ? 1 : 0.24, alpha: mine ? 0.15 : 1))
    }

    /// 1 つの吹き出し (= 中身を組み、 地の大きさを決める)
    static func layout(_ text: String, mine: Bool) -> (content: ChatMarkdown, size: CGSize) {
        let content = ChatMarkdown(markdown: text, width: contentWidth(mine: mine), style: style(mine: mine))
        return (content, CGSize(width: content.size.width + padding.width * 2, height: content.size.height + padding.height * 2))
    }
}
