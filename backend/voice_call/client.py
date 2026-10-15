"""電話の会話の process が backend を呼ぶ口 (= 画面と同じ公開の口だけを使う 1 つの client)。

会話は、 音の送り出しを止めないために backend 本体と別の process で動く (= `worker.py`)。 聞き取り・声の合成・
文の切り分け・タブへの送信・返事の stream・会話の持ち主は、 全部 backend の口を通す (= 決まりの真値は backend に
1 つ)。
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

import aiohttp

from backend.voice_call.rules import mark_voice_input


class ConversationLost(Exception):
    """そのタブの会話を、 別の画面が開いた (= `voice_conversation_elsewhere`)。"""


class BackendClient:
    def __init__(self, base_url: str, session_id: str, client: str):
        self._base = base_url.rstrip("/")
        self._sid = session_id
        self._voice = f"{self._base}/sessions/{quote(session_id)}/voice"
        self.client = client
        self._http: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> BackendClient:
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http:
            await self._http.close()

    async def _json(self, method: str, url: str, **kwargs):
        async with self._http.request(method, url, **kwargs) as r:
            body = await r.json(content_type=None)
            if r.status == 409 and (body or {}).get("detail", {}).get("code") == "voice_conversation_elsewhere":
                raise ConversationLost()
            if r.status >= 400:
                raise RuntimeError(f"{method} {url} -> {r.status} {body}")
            return body

    async def claim(self) -> None:
        await self._json("POST", f"{self._voice}/conversation", json={"client": self.client})

    async def release(self) -> None:
        await self._json("DELETE", f"{self._voice}/conversation", json={"client": self.client})

    async def transcribe(self, wav: bytes) -> str:
        headers = {"Content-Type": "audio/wav", "X-Voice-Conversation": self.client}
        body = await self._json("POST", f"{self._voice}/transcription", data=wav, headers=headers)
        return (body.get("text") or "").strip()

    async def utterances(self, text: str) -> list[dict]:
        return (await self._json("POST", f"{self._voice}/utterances", json={"text": text})).get("utterances") or []

    async def synthesize(self, text: str, mark: str | None, values: dict | None = None) -> bytes:
        body = {"text": text, **({"mark": mark} if mark else {}), **({"values": values} if values else {})}
        async with self._http.post(f"{self._voice}/synthesis", json=body) as r:
            if r.status >= 400:
                raise RuntimeError(f"synthesis -> {r.status} {await r.text()}")
            return await r.read()

    async def send(self, text: str) -> bool:
        """そのタブへ 1 通送る (= 画面で打った時と同じ口。 声で聞いている印を付ける)。"""
        body = {"text": mark_voice_input(text), "enter": True}
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        result = await self._json("POST", f"{self._base}/pty/{quote(self._sid)}/send", json=body, headers=headers)
        return bool(result.get("ok"))

    async def events(self) -> AsyncIterator[dict]:
        """そのタブの event を、 届いた順に返し続ける (= 画面と同じ統合 stream)。"""
        params = {"conn": f"voice-call-{uuid.uuid4().hex[:12]}", "jsonl": self._sid}
        async with self._http.get(f"{self._base}/stream/unified", params=params) as r:
            async for raw in r.content:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    frame = json.loads(line[5:])
                except ValueError:
                    continue
                if frame.get("ch") == "jsonl" and isinstance(frame.get("ev"), dict):
                    yield frame["ev"]
