"""backend._common.prose_language の単体テスト。

設定が日本語の時に英語の地の文だけを拾い、 日本語の文・頼まれた英文・英語の名前の並びは通すことを、
1 文ずつ確かめる。
"""
import json
import os

import pytest

from backend._common import prose_language
from backend._common.prose_language import configured_language, foreign_prose

EN = "The fix is ready. The only thing left before I merge and deploy it is the GitHub check, which has not finished yet."
JA = "直しを作り終えました。 GitHub の検査が終わるのを待ってから merge して、 本番に入れます。 試験は全部緑です。"
ASKED = """会議でそのまま読めるように、 英語の自己紹介を 30 秒くらいの長さで書きました。

Hi everyone, I'm from the research team. I studied chemistry, and now I build tools that turn recordings into data people can trust. Most of my week goes into the software that records the sessions, checks every file as it is written, and keeps the results comparable across months."""
QUOTED = "You said 「やって」, so I'll run the full suite now, merge the branch once the GitHub check has finished, and restart the backend after that."
NAMED = "Next I'm rewriting one line in the 本棚 notes and writing the rule-firing log for this session before I close."
INCODE = """I'll add this line to the notes file, run the whole test suite again, and commit it once every check has passed:
```
- 起動の手順はいつもどおり全部踏む
```"""
BLOCKQ = """> 全部テストしてから入れてほしい。 それと、 終わったら教えてね。
Got it. I'll run every test first, merge only when all of them pass, and tell you as soon as it is in production."""
UNCLOSED = """結果はこうなりました。
```
The build finished without errors and the frontend bundle was written to the dist folder for the backend to serve."""
REPORT = """移行完了:
- SessionListProvider / ConversationView / MarkdownRenderer
- WebSocketReconnect / BackoffPolicy / PushSubscriptionStore"""
NAMES = "SessionListProvider ConversationView MarkdownRenderer WebSocketReconnect BackoffPolicy PushSubscriptionStore"


@pytest.mark.parametrize("text", [EN, QUOTED, NAMED, INCODE, BLOCKQ])
def test_english_prose_is_foreign_when_japanese(text):
    assert foreign_prose(text, "日本語")


@pytest.mark.parametrize("text", [JA, ASKED, UNCLOSED, REPORT, NAMES, "OK.", ""])
def test_japanese_requested_english_and_names_pass(text):
    assert not foreign_prose(text, "日本語")


@pytest.mark.parametrize("language", ["English", "", None])
def test_other_languages_hold_nothing(language):
    assert not foreign_prose(EN, language)


@pytest.mark.parametrize("language", ["japanese", "ja", "JA-JP", " 日本語 "])
def test_japanese_spellings(language):
    assert foreign_prose(EN, language)


def test_configured_language_reads_and_follows_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(prose_language, "_cache", {})
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"language": "日本語"}), encoding="utf-8")
    assert configured_language(tmp_path) == "日本語"
    settings.write_text(json.dumps({"language": "English"}), encoding="utf-8")
    stat = settings.stat()
    os.utime(settings, (stat.st_atime, stat.st_mtime + 5))
    assert configured_language(tmp_path) == "English"


def test_configured_language_missing_or_broken_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(prose_language, "_cache", {})
    assert configured_language(tmp_path) == ""
    (tmp_path / "settings.json").write_text("not json", encoding="utf-8")
    assert configured_language(tmp_path) == ""
    (tmp_path / "settings.json").write_text("[]", encoding="utf-8")
    assert configured_language(tmp_path) == ""
