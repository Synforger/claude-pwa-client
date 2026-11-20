"""Rows of a conversation record for the error resume's tests: the rows Claude Code writes when an API error ends a
turn (the shapes read from Claude Code 2.1.328), and the client's message to carry on."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.error_resume.error_envelope import resume_envelope
from backend.sleep.record_facts import ErrorStop

CUT_WORDS = "API Error: Connection lost mid-response. The response above may be incomplete."


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, tz=timezone.utc).isoformat()


def error_row(uuid: str = "err1", at: float | None = None, *, error: str = "server_error", api_error: str | None = None,
              transient: bool | None = None, words: str = CUT_WORDS, sidechain: bool = False,
              cut: str | None = None) -> dict:
    row = {"type": "assistant", "uuid": uuid, "isApiErrorMessage": True, "error": error,
           "message": {"role": "assistant", "content": [{"type": "text", "text": words}]}}
    if at is not None:
        row["timestamp"] = iso(at)
    if api_error is not None:
        row["apiError"] = api_error
    if transient is not None:
        row["apiErrorIsTransient"] = transient
    if sidechain:
        row["isSidechain"] = True
    if cut is not None:
        row["streamCutCause"] = cut
    return row


def prompt(text: str = "go on", at: float | None = None, *, origin: str | None = "human") -> dict:
    row: dict = {"type": "user", "message": {"role": "user", "content": text}}
    if origin is not None:
        row["origin"] = {"kind": origin}
    if at is not None:
        row["timestamp"] = iso(at)
    return row


def said(text: str = "working", at: float | None = None) -> dict:
    row = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if at is not None:
        row["timestamp"] = iso(at)
    return row


def hidden(at: float | None = None) -> dict:
    """The hidden user row Claude Code writes before it carries a cut reply on by itself."""
    row = {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Continue from where you left off."}}
    if at is not None:
        row["timestamp"] = iso(at)
    return row


def resume_prompt(at: float | None = None, streak: int = 0) -> dict:
    """The client's message to carry on, as Claude Code records a message typed into the terminal."""
    stop = ErrorStop(uuid="x", at=0.0, error="server_error", cause="", words=CUT_WORDS)
    return prompt(resume_envelope(stop, streak), at)
