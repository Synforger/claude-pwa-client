"""tmux capture-pane -e 出力の ANSI SGR 解析 (= pure、 I/O なし)。

prompt_detector の tier B が使う。 テキストの「文字の並び」 だけでは picker の選択行と
チャット本文の番号リストを区別できない (= 2026-07-06 の誤爆 class)。 実際の画面は
選択行を色 / 反転で表現しているので、 SGR 装飾を構造情報として読む:

- `strip_ansi(text)`             — escape 除去の plain text 化 (= 従来 -p 相当)
- `line_style_signatures(text)`  — 行ごとの「可視文字に効いていた SGR 属性集合」

装飾の意味論 (= 色番号が何色か) には立ち入らない。 使うのは「行の装飾が兄弟行と
違うか」「装飾が一切無いか」 という比較のみ (= テーマ / 配色に依存しない)。
"""
from __future__ import annotations

import re

# SGR (= Select Graphic Rendition、 `ESC [ ... m`)。 色 / 太字 / 反転等の装飾のみ。
_SGR_RE = re.compile(r"\x1b\[([0-9;:]*)m")

# SGR 以外の escape sequence (= カーソル移動 CSI / OSC タイトル / charset 指定等)。
# plain 化で除去する。 capture-pane -e の実出力は SGR が大半だが、 防御的に広く払う。
_OTHER_ESCAPE_RE = re.compile(
    r"\x1b(?:"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC ... BEL / ST
    r"|\[[0-9;:?]*[A-LN-Za-ln-z]"      # CSI (= 終端 m 以外)
    r"|[()][0-9A-B]"                   # charset 指定
    r"|[=>M78]"                        # keypad / reverse index / save-restore
    r")"
)

# 前景 / 背景色の基本コード (= 39 / 49 のリセット対象判定に使う)。
_FG_BASE = {str(n) for n in range(30, 38)} | {str(n) for n in range(90, 98)} | {"38"}
_BG_BASE = {str(n) for n in range(40, 48)} | {str(n) for n in range(100, 108)} | {"48"}


def strip_ansi(text: str) -> str:
    """全 escape sequence を除去して plain text を返す (= capture-pane -p 相当)。"""
    return _OTHER_ESCAPE_RE.sub("", _SGR_RE.sub("", text))


def _apply_sgr_params(active: set[str], params: str) -> None:
    """SGR パラメータ列を active 属性集合に反映する (= 破壊的更新)。

    38/48 の拡張色 (= `38;5;N` / `38;2;R;G;B`) は 1 属性トークンに束ねる。
    reset 系 (0 / 39 / 49 / 22-29) は該当属性を落とす。 それ以外は追加。
    """
    toks = params.split(";") if params else [""]
    i = 0
    while i < len(toks):
        t = toks[i]
        base = t.split(":")[0]
        if t == "" or base == "0":
            active.clear()
        elif base in ("38", "48") and ":" not in t:
            # `38;5;N` / `38;2;R;G;B` — 後続トークンを束ねて 1 属性に
            if i + 1 < len(toks) and toks[i + 1] == "5" and i + 2 < len(toks):
                bundle = ";".join(toks[i:i + 3])
                i += 2
            elif i + 1 < len(toks) and toks[i + 1] == "2" and i + 4 < len(toks):
                bundle = ";".join(toks[i:i + 5])
                i += 4
            else:
                bundle = t
            active.difference_update(
                a for a in list(active)
                if a.split(";")[0].split(":")[0] in (_FG_BASE if base == "38" else _BG_BASE)
            )
            active.add(bundle)
        elif base == "39":
            active.difference_update(
                a for a in list(active) if a.split(";")[0].split(":")[0] in _FG_BASE
            )
        elif base == "49":
            active.difference_update(
                a for a in list(active) if a.split(";")[0].split(":")[0] in _BG_BASE
            )
        elif base == "22":
            active.discard("1")
            active.discard("2")
        elif base in ("23", "24", "25", "27", "28", "29"):
            active.discard(str(int(base) - 20))
        else:
            if base in _FG_BASE:
                active.difference_update(
                    a for a in list(active) if a.split(";")[0].split(":")[0] in _FG_BASE
                )
            elif base in _BG_BASE:
                active.difference_update(
                    a for a in list(active) if a.split(";")[0].split(":")[0] in _BG_BASE
                )
            active.add(t)
        i += 1


def line_style_signatures(text: str) -> list[frozenset[str]]:
    """行ごとに「可視 (= 非空白) 文字へ効いていた SGR 属性の集合」 を返す。

    SGR 状態は行を跨いで持続する (= capture 出力は行頭で再宣言しない) ので、 全文を
    逐次走査して行境界で snapshot する。 空 frozenset = その行の可視文字は全て
    デフォルト装飾 (or 可視文字なし)。
    """
    sigs: list[frozenset[str]] = []
    active: set[str] = set()
    for line in text.split("\n"):
        seen: set[str] = set()
        idx = 0
        for m in _SGR_RE.finditer(line):
            seg = _OTHER_ESCAPE_RE.sub("", line[idx:m.start()])
            if seg.strip():
                seen |= active
            _apply_sgr_params(active, m.group(1))
            idx = m.end()
        seg = _OTHER_ESCAPE_RE.sub("", line[idx:])
        if seg.strip():
            seen |= active
        sigs.append(frozenset(seen))
    return sigs
