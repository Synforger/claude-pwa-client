"""SPA (= frontend/dist) を配信する StaticFiles の派生。

置き場が `backend/_internal/` なのは compression.py と同じ理由で、 app 組み立て (= main.py) から
独立して単体で試験できる形にしておくため。 main.py を import すると logging 初期化と全 router
の登録が走るので、 配信の振る舞いだけを見たい test がそれに引きずられない。
"""
from __future__ import annotations

from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketClose


class CacheControlledStaticFiles(StaticFiles):
    """The entry page is never stored, manifest.json / sw.js are revalidated, hashed assets are cached for good.

    The entry page names the build's hashed assets, so a stale copy boots an old build. iOS WebKit, when it
    brings back a page it dropped in the background, takes the entry page from its HTTP cache without asking
    the backend, even under no-cache; only no-store keeps it from having a copy to take. That matters where no
    service worker stands in between (the iPhone app); the service worker fetches it with no-store itself
    (frontend/public/sw.js) and keeps its own copy for offline starts. /assets/ file names carry a content hash,
    so they never need checking.
    """

    NO_STORE_PATHS = {"", ".", "index.html"}
    NO_CACHE_PATHS = {"manifest.json", "sw.js"}
    IMMUTABLE_PREFIX = "assets/"

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        normalized = path.lstrip("/")
        if normalized in self.NO_STORE_PATHS:
            response.headers["Cache-Control"] = "no-store"
        elif normalized in self.NO_CACHE_PATHS:
            response.headers["Cache-Control"] = "no-cache"
        elif normalized.startswith(self.IMMUTABLE_PREFIX):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    async def __call__(self, scope, receive, send):
        """SPA mount は "/" 配下を全部受けるので、 どの WS route にも当たらなかった
        websocket 接続もここへ落ちてくる。 StaticFiles は http scope を前提に assert する
        ため、 そのまま渡すと AssertionError が unhandled 例外として立ち、 「エラーが出て
        いる」 とだけ見える形で log を汚す (= 実測 13 件、 出所は 2026-07-27 に退役した
        `/views/ws` へ繋ぎ続けている古い bundle)。

        静的配信が扱うのは http だけ。 websocket は route 不在として閉じる (= route が
        1 つも当たらなかった時の starlette 既定と同じ振る舞いに合わせる)。
        """
        if scope["type"] != "http":
            await WebSocketClose()(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
