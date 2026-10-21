"""資料の HTML の頁 (= 変換結果・変換の待ち・失敗・Markdown)。

どれもスクリプトを持たない (= 待ちの画面は `<meta refresh>` で自分を読み直す)。 `/file/view` の sandbox
(= `connect-src 'none'`) の下でも、 ページの origin の下でも、 同じ頁が出る。
"""
from __future__ import annotations

import html
from backend.documents import strings
from backend.documents.convert import ConversionError

_CSS = """
:root { --bg: #f4f5f7; --surface: #fff; --fg: #1b2230; --muted: #5d6877; --line: #d6dbe3; --accent: #2856c9; --code: #eef0f4; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #12171e; --surface: #19202a; --fg: #e3e9f0; --muted: #94a2b2; --line: #2b3542; --accent: #86a8ff; --code: #10151c; color-scheme: dark; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.8 system-ui, -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif;
  padding: 16px max(16px, env(safe-area-inset-right)) 48px max(16px, env(safe-area-inset-left)); }
.wrap { max-width: 1080px; margin: 0 auto; display: grid; gap: 16px; min-width: 0; }
h1 { font-size: 1.3rem; line-height: 1.4; margin: 0; overflow-wrap: anywhere; }
a { color: var(--accent); }
.meta { color: var(--muted); font: 12px ui-monospace, Menlo, monospace; overflow-wrap: anywhere; margin: 4px 0 0; }
figure.page { margin: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
figure.page img { display: block; width: 100%; height: auto; background: #fff; }
figure.page figcaption { color: var(--muted); font: 12px ui-monospace, Menlo, monospace; margin-top: 4px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; min-width: 0; }
.status { display: flex; gap: 12px; align-items: center; }
.spinner { flex: none; width: 22px; height: 22px; border: 3px solid var(--line); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.status p { margin: 0; }
.hint { color: var(--muted); font-size: 13px; }
.doc { overflow-wrap: anywhere; }
.doc h1, .doc h2, .doc h3, .doc h4 { line-height: 1.4; margin: 1.4em 0 0.4em; }
.doc h1 { font-size: 1.55rem; }
.doc h2 { font-size: 1.3rem; }
.doc h3 { font-size: 1.1rem; }
.doc h4 { font-size: 1rem; }
.doc h1:first-child { margin-top: 0; }
.doc p, .doc ul, .doc ol, .doc pre, .doc blockquote, .doc .tablewrap { margin: 0.6em 0; }
.doc ul, .doc ol { padding-left: 1.4em; }
.doc pre { background: var(--code); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; overflow-x: auto; }
.doc pre code { white-space: pre; overflow-wrap: normal; }
code { font: 12.5px ui-monospace, Menlo, monospace; overflow-wrap: anywhere; }
.doc :not(pre) > code { background: var(--code); border-radius: 4px; padding: 0 4px; }
.doc blockquote { border-left: 3px solid var(--line); padding-left: 12px; color: var(--muted); margin-left: 0; }
.doc img { max-width: 100%; height: auto; }
.doc hr { border: 0; border-top: 1px solid var(--line); }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; font-size: 13.5px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.missing { display: inline-block; color: var(--muted); border: 1px dashed var(--line); border-radius: 6px; padding: 2px 10px; font-size: 13px; }
"""


def _shell(title: str, body: str, lang: str, head: str = "") -> str:
    return (
        f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"{head}<title>{html.escape(title)}</title>\n<style>{_CSS}</style>\n</head>\n"
        f'<body>\n<div class="wrap">\n{body}\n</div>\n</body>\n</html>\n'
    )


def _header(name: str, shown_path: str, extra: str = "") -> str:
    sub = " ／ ".join(part for part in (extra, shown_path) if part)
    return f'<header><h1>{html.escape(name)}</h1><p class="meta">{html.escape(sub)}</p></header>'


def ready(name: str, url_name: str, shown_path: str, key: str, sizes: list[tuple[int, int]], lang: str) -> str:
    """頁の画像を縦に並べた頁。 画像は同じ URL に `?page=N&v=<key>` を付けて読む (= 元の file が変わると key が変わる)。

    `url_name` = 要求された URL の最後の部分 (= 符号化済み。 symlink 越しでも、 画像は要求と同じ場所から読む)。
    """
    figures = []
    for n, (width, height) in enumerate(sizes, 1):
        figures.append(
            f'<figure class="page" id="p{n}"><img src="{url_name}?page={n}&amp;v={key}" width="{width}" height="{height}" '
            f'loading="lazy" alt="{html.escape(strings.text(lang, "page_alt", n=n))}">'
            f'<figcaption><a href="#p{n}">{html.escape(strings.text(lang, "page_caption", n=n, total=len(sizes)))}</a></figcaption></figure>'
        )
    body = _header(name, shown_path, strings.text(lang, "pages", n=len(sizes))) + "\n" + "\n".join(figures)
    return _shell(name, body, lang)


def waiting(name: str, url_name: str, shown_path: str, phase: str, elapsed: float, lang: str) -> str:
    key = {"office": "phase_office", "render": "phase_render"}.get(phase, "phase_start")
    body = (
        _header(name, shown_path)
        + '\n<div class="card status"><div class="spinner" role="progressbar"></div><div>'
        + f'<p>{html.escape(strings.text(lang, "converting"))} {html.escape(strings.text(lang, key, s=int(elapsed)))}</p>'
        + f'<p class="hint">{html.escape(strings.text(lang, "converting_hint"))}</p></div></div>'
    )
    return _shell(name, body, lang, head=f'<meta http-equiv="refresh" content="2;url={url_name}">\n')


def failed(name: str, shown_path: str, error: ConversionError, lang: str) -> str:
    reason = strings.text(lang, f"reason_{error.code}", **error.params)
    body = (
        _header(name, shown_path)
        + f'\n<div class="card"><p><b>{html.escape(strings.text(lang, "failed"))}</b></p><p>{html.escape(reason)}</p>'
        + f'<p><a href="?retry=1">{html.escape(strings.text(lang, "retry"))}</a></p></div>'
    )
    return _shell(name, body, lang)


def markdown(name: str, shown_path: str, rendered: str, title: str | None, lang: str) -> str:
    body = _header(name, shown_path) + f'\n<article class="card doc">{rendered}</article>'
    return _shell(title or name, body, lang)
