# backend tests

Add pytest test files here as `test_*.py`. Run via `task test:unit`
from the repo root (= `python -m pytest backend/tests`).

The folders mirror the backend tree: a test for `backend/jsonl/session_status.py`
lives in `backend/tests/jsonl/`. The ones that are not a backend folder:

| Folder | What it holds |
|---|---|
| `architecture/` | gates over the whole backend (= the layering rule) |
| `contracts/` | the checked-in contracts against the code |
| `integration/` | tests that go through several parts at once |
| `tooling/` | tests of the scripts outside `backend/` (= iPhone crash reports, the privacy check) |

`conftest.py` and the fixtures shared by every folder stay here.
