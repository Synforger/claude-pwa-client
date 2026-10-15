"""iPhone の Board のウィジェットに出す中身 (= Mac の agent が `cpc device widget set` で置く)。

board は名前で分かれ、 1 つが 1 枚のウィジェットの中身になる (= ウィジェットは長押しの編集で、 どの board を出すかを
選ぶ。 選んでいなければ `main`)。 1 つの board が持つのは見出し・本文・大きく出す短い値と、 押した時に開くタブ。
置いた物は file (= `data/device_boards.json`) が真値で、 backend を立ち上げ直しても残る。

    {"boards": {"main": {"title": "...", "text": "...", "value": "...", "tab": "<sid>", "updated_at": 秒}}}
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# 何も選んでいないウィジェットが出す board
DEFAULT_BOARD = "main"
# board の名前に使ってよい文字 (= ウィジェットの編集の一覧に出る)
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
# 1 つの board が持つ欄 (= どれも文字。 無い欄はウィジェットに出ない)
FIELDS = ("title", "text", "value", "tab")


class BadBoard(ValueError):
    """名前か中身の形が違う。"""


class BoardStore:
    """board の中身を file に持つ。"""

    def __init__(self, path: Path):
        self._path = path

    def all(self) -> dict[str, dict]:
        try:
            saved = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}
        boards = saved.get("boards") if isinstance(saved, dict) else None
        return {name: board for name, board in (boards or {}).items() if isinstance(board, dict)}

    def get(self, name: str) -> dict | None:
        return self.all().get(self._name(name))

    def set(self, name: str, content: dict) -> dict:
        """board を置き換える (= 渡さなかった欄は消える)。"""
        name = self._name(name)
        if not isinstance(content, dict):
            raise BadBoard("the board is an object")
        unknown = sorted(set(content) - set(FIELDS))
        if unknown:
            raise BadBoard(f"unknown fields: {', '.join(unknown)} (a board has {', '.join(FIELDS)})")
        board: dict = {}
        for field in FIELDS:
            value = content.get(field)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise BadBoard(f"{field} is text")
            text = str(value)
            if text:
                board[field] = text
        if not any(board.get(field) for field in ("title", "text", "value")):
            raise BadBoard("give at least one of title, text and value (clear removes a board)")
        board["updated_at"] = time.time()
        boards = self.all()
        boards[name] = board
        self._write(boards)
        return board

    def clear(self, name: str) -> bool:
        """board を消す (= 在ったかを返す)。"""
        name = self._name(name)
        boards = self.all()
        if boards.pop(name, None) is None:
            return False
        self._write(boards)
        return True

    @staticmethod
    def _name(name: str) -> str:
        if not isinstance(name, str) or not _NAME.match(name):
            raise BadBoard("a board name is 1-32 letters, digits, '-' or '_'")
        return name

    def _write(self, boards: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".tmp")
        temp.write_text(json.dumps({"boards": boards}, ensure_ascii=False, indent=1))
        temp.replace(self._path)
