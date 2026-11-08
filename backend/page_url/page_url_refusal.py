"""Why a page has no tailnet URL: the error `page_url` and `tailnet` raise and `backend/routes/page_url.py` answers with."""

from __future__ import annotations


class PageUrlRefusal(Exception):
    """A page URL could not be made. `code` is the error code the endpoint answers with, `message` says why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
