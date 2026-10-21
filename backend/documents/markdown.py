"""Markdown を HTML にする (= 資料の頁の本文)。

書いた人の HTML は通さず (= 文字として出す)、 見出しには GitHub と同じ作りの id を付ける。 資料の頁は元の file と
同じ path で配るので、 相対のリンクと図は書いたとおりに届く。 ここでは次の 3 つだけを扱う:

- 図の file が無い (または配れない) 時は、 壊れた画像ではなく「見つからない」 と分かる枠にする
- 目次のリンクの語が見出しと合っていない時は、 リンクの語が順に含まれる最初の見出しへ張り直す
  (= 番号や括弧の中を省いた目次。 同じ file の見出しにも、 別の md の見出しへのリンクにも掛ける)
- 外の画像は、 頁が外へ通信できない (= CSP) ので読み込まず、 そう分かる枠にする
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.token import Token

from backend.documents import strings

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*(?:\n|\Z)", re.DOTALL)
_BR_RE = re.compile(r"&lt;br\s*/?&gt;", re.IGNORECASE)


@dataclass
class Neighbors:
    """md の隣に在る file を、 配れるかどうか (= 今の口と同じ検査で) 答える物。"""
    base_dir: Path
    is_served: Callable[[Path], bool]
    read_markdown: Callable[[Path], str | None]


def slugify(text: str) -> str:
    """GitHub の見出しの id と同じ作り (= 小文字・記号を消す・空白は `-`)。"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*]", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def fix_anchor(fragment: str, slugs: list[str]) -> str:
    """見出しの id に無い断片は、 語が順に含まれる最初の見出しの id にする (= 無ければそのまま)。"""
    if fragment in slugs:
        return fragment
    want = fragment.replace("-", "")
    if not want:
        return fragment
    for slug in slugs:
        rest = iter(slug.replace("-", ""))
        if all(char in rest for char in want):
            return slug
    return fragment


def _inline_text(token: Token) -> str:
    return "".join(c.content for c in (token.children or []) if c.type in ("text", "code_inline"))


def _heading_slugs(tokens: list[Token]) -> list[str]:
    """見出しの順に id を決めて token に付ける (= 同じ語の見出しは `-1` `-2` を足す)。"""
    seen: dict[str, int] = {}
    slugs: list[str] = []
    for i, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        slug = slugify(_inline_text(tokens[i + 1]))
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        if n:
            slug = f"{slug}-{n}"
        token.attrSet("id", slug)
        slugs.append(slug)
    return slugs


def _slugs_of(text: str) -> list[str]:
    return _heading_slugs(_parser().parse(_without_front_matter(text)[1]))


def _without_front_matter(text: str) -> tuple[str, str]:
    """(= 先頭の `---` で囲んだ設定の塊, 残り)。"""
    match = _FRONT_MATTER_RE.match(text)
    return (match.group(1), text[match.end():]) if match else ("", text)


def _parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "breaks": False}).enable(["table", "strikethrough"])

    def text(self, tokens, idx, options, env):
        # `<br>` だけは表の中の改行に使われるので、 改行として通す
        return _BR_RE.sub("<br>", escapeHtml(tokens[idx].content))

    md.add_render_rule("text", text)
    md.add_render_rule("table_open", lambda self, tokens, idx, options, env: '<div class="tablewrap"><table>\n')
    md.add_render_rule("table_close", lambda self, tokens, idx, options, env: "</table></div>\n")
    return md


def _missing(label: str, shown: str) -> Token:
    token = Token("html_inline", "", 0)
    token.content = f'<span class="missing">{html.escape(label)} <code>{html.escape(shown)}</code></span>'
    return token


def _external_image(label: str, url: str) -> Token:
    token = Token("html_inline", "", 0)
    token.content = f'<span class="missing">{html.escape(label)} <a href="{html.escape(url)}">{html.escape(url)}</a></span>'
    return token


def _local_path(neighbors: Neighbors, url: str) -> Path:
    return neighbors.base_dir / unquote(urlsplit(url).path)


def _rewrite_link(token: Token, own_slugs: list[str], own_name: str, neighbors: Neighbors) -> None:
    href = token.attrGet("href") or ""
    if not href or _SCHEME_RE.match(href):
        token.attrSet("rel", "noreferrer")
        return
    parts = urlsplit(href)
    if not parts.fragment:
        return
    wanted = unquote(parts.fragment).lower()
    target_name = unquote(parts.path)
    if not target_name or os.path.normpath(target_name) == own_name:
        slugs = own_slugs
    elif target_name.lower().endswith((".md", ".markdown")):
        target = neighbors.base_dir / target_name
        text = neighbors.read_markdown(target) if neighbors.is_served(target) else None
        slugs = _slugs_of(text) if text is not None else []
    else:
        return
    fixed = fix_anchor(wanted, slugs)
    token.attrSet("href", urlunsplit(parts._replace(fragment=quote(fixed, safe=""))))


def render(text: str, neighbors: Neighbors, own_name: str, lang: str) -> tuple[str, str | None]:
    """(= 本文の HTML, 最初の見出しの文字) を返す。"""
    front, body = _without_front_matter(text)
    md = _parser()
    env: dict = {}
    tokens = md.parse(body, env)
    slugs = _heading_slugs(tokens)
    title = None
    for i, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h1":
            title = _inline_text(tokens[i + 1]) or None
            break
    for block in tokens:
        for i, child in enumerate(block.children or []):
            if child.type == "link_open":
                _rewrite_link(child, slugs, own_name, neighbors)
            elif child.type == "image":
                src = child.attrGet("src") or ""
                shown = unquote(src)
                if _SCHEME_RE.match(src) and not src.lower().startswith("data:"):
                    block.children[i] = _external_image(strings.text(lang, "image_external"), src)
                elif not _SCHEME_RE.match(src) and not neighbors.is_served(_local_path(neighbors, src)):
                    block.children[i] = _missing(strings.text(lang, "image_missing"), shown)
                else:
                    child.attrSet("loading", "lazy")
    rendered = md.renderer.render(tokens, md.options, env)
    if front:
        rendered = f'<pre class="front-matter"><code>{html.escape(front.rstrip())}</code></pre>\n' + rendered
    return rendered, title
