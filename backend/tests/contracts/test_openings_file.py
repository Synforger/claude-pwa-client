"""`contracts/openings.txt` lists the first lines of the messages the client types into a tab itself, for the tools
outside the client that read it (the guard, hooks of the agents). The source is `CLIENT_OPENINGS`; the two must say the
same, in the same order."""
from __future__ import annotations

from pathlib import Path

from backend.jsonl.jsonl_predicates import CLIENT_OPENINGS

OPENINGS_FILE = Path(__file__).resolve().parents[3] / "contracts" / "openings.txt"
FIX = "contracts/openings.txt を直す (真値は backend/jsonl/jsonl_predicates.py の CLIENT_OPENINGS。 1 行 1 つ、 頭に `>`)"


def _lines() -> list[str]:
    """The lines of the file that are not blank and not comments."""
    return [line for line in OPENINGS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def test_every_line_of_the_file_is_an_opening_marked_with_a_head_arrow():
    bad = [line for line in _lines() if not line.startswith(">") or not line[1:].strip()]
    assert not bad, f"lines that are not `>` and a first line: {bad}. {FIX}"


def test_the_file_lists_exactly_the_first_lines_the_client_writes_and_in_their_order():
    listed = [line[1:] for line in _lines()]
    missing = [line for line in CLIENT_OPENINGS if line not in listed]
    extra = [line for line in listed if line not in CLIENT_OPENINGS]
    assert not missing, f"first lines the client writes that the file lacks: {missing}. {FIX}"
    assert not extra, f"first lines in the file that the client does not write: {extra}. {FIX}"
    assert listed == list(CLIENT_OPENINGS), f"the lines are in another order or repeated. {FIX}"


def test_the_file_says_what_it_is_for_in_its_first_comment_lines():
    head = OPENINGS_FILE.read_text(encoding="utf-8").splitlines()[:4]
    assert all(line.startswith("#") for line in head) and "CLIENT_OPENINGS" in " ".join(head)
