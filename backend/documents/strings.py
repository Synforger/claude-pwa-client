"""資料の頁に出す文言 (= 利用者の言語は `Accept-Language` で選ぶ。 画面側の i18n と同じく ja / en)。"""
from __future__ import annotations

_STRINGS = {
    "en": {
        "pages": "{n} pages",
        "page_caption": "p. {n} / {total}",
        "page_alt": "Page {n}",
        "converting": "Converting…",
        "converting_hint": "The first time a file is opened it is turned into page images. This page refreshes by itself.",
        "phase_office": "Converting to PDF ({s} s)",
        "phase_render": "Making page images ({s} s)",
        "phase_start": "Starting ({s} s)",
        "failed": "This file could not be opened",
        "retry": "Try again",
        "image_missing": "Image not found:",
        "image_external": "External image, not loaded:",
        "reason_missing_tool": "{tool} is not installed on the machine running the backend.",
        "reason_timeout": "Converting took longer than {s} seconds, so it was stopped.",
        "reason_protected": "The file is password-protected.",
        "reason_unreadable": "The converter could not read this file.",
        "reason_no_pages": "The file produced no pages.",
        "reason_failed": "Converting failed.",
    },
    "ja": {
        "pages": "{n} ページ",
        "page_caption": "{n} / {total} ページ",
        "page_alt": "{n} ページ目",
        "converting": "変換しています…",
        "converting_hint": "初めて開く file は、 ページの画像に変えます。 この画面は自動で更新されます。",
        "phase_office": "PDF に変換中 ({s} 秒)",
        "phase_render": "ページの画像を作成中 ({s} 秒)",
        "phase_start": "開始しています ({s} 秒)",
        "failed": "この file は開けませんでした",
        "retry": "もう一度試す",
        "image_missing": "図が見つかりません：",
        "image_external": "外部の画像は読み込みません：",
        "reason_missing_tool": "backend を動かしている機械に {tool} が入っていません。",
        "reason_timeout": "変換に {s} 秒を超えたので止めました。",
        "reason_protected": "file にパスワードが掛かっています。",
        "reason_unreadable": "変換の道具がこの file を読めませんでした。",
        "reason_no_pages": "変換しても 1 ページも出ませんでした。",
        "reason_failed": "変換に失敗しました。",
    },
}


def pick_language(accept_language: str | None) -> str:
    """`Accept-Language` の先頭が日本語なら ja、 それ以外は en。"""
    first = (accept_language or "").split(",")[0].strip().lower()
    return "ja" if first.startswith("ja") else "en"


def text(lang: str, key: str, **params) -> str:
    return _STRINGS.get(lang, _STRINGS["en"])[key].format(**params)
