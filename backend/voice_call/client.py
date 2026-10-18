"""電話の会話の process が backend を呼ぶ口 (= 画面と同じ公開の口だけを使う 1 つの client)。

会話は、 音の送り出しを止めないために backend 本体と別の process で動く (= `worker.py`)。 聞き取り・声の合成・
文の切り分け・タブへの送信・返事の stream・会話の持ち主は、 全部 backend の口を通す (= 決まりの真値は backend に
1 つ)。
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

import aiohttp

from backend.voice_call.rules import mark_voice_input

logger = logging.getLogger(__name__)


class ConversationLost(Exception):
    """そのタブの会話を、 別の画面が開いた (= `voice_conversation_elsewhere`)。"""


class BackendClient:
    def __init__(self, base_url: str, session_id: str, client: str):
        self._base = base_url.rstrip("/")
        self._sid = session_id
        self._voice = f"{self._base}/sessions/{quote(session_id)}/voice"
        self.client = client
        self._http: aiohttp.ClientSession | None = None
        # 返事の stream の接続の名前 (= 停止の印を、 画面の停止ボタンと同じ制御の口で付ける)
        self._conn = f"voice-call-{uuid.uuid4().hex[:12]}"

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

    async def stop(self) -> None:
        """そのタブの turn を止める (= 画面の停止ボタンと同じ 2 つ: Escape で止めて入力欄に戻された文を消し、 停止の
        印を付ける。 印が付くと、 次の発話まで作業中と見なされない)。"""
        await self._json("POST", f"{self._base}/pty/{quote(self._sid)}/send", json={"key": "Escape"})
        await self._json("POST", f"{self._base}/stream/unified/{self._conn}/control",
                         json={"op": "stop", "sid": self._sid})

    async def reading(self, text: str) -> str:
        """文の読み (= engine が声にする時の拍のカナ)。 読めなければ空文字 (= 自分の声の見分けに使うだけなので、
        engine が止まっていても会話は続ける)。"""
        try:
            return (await self._json("POST", f"{self._voice}/reading", json={"text": text})).get("reading") or ""
        except ConversationLost:
            raise
        except Exception as error:  # noqa: BLE001
            logger.info("voice call: no reading for %d chars: %s", len(text), error)
            return ""

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
        """そのタブの event を、 届いた順に返し続ける (= 画面と同じ統合 stream)。

        記録の event に加えて、 タブが作業中かが変わったら `{"type": "busy", "busy": bool}` を返す (= 画面の青丸と
        停止ボタンと同じ値。 つないだ直後に 1 回)。

        ⚠ 行は長さに関わらず読む。 aiohttp の行読み (= `async for … in r.content`) は 128 KB を超える 1 行で
        `LineTooLong` を出して止まる。 記録には画像を読んだ結果のような 1 MB を超える行が入り、 つなぐたびに読み直しが
        そこで止まって、 その後の返事が声にも小窓にも出なくなった。
        """
        params = {"conn": self._conn, "jsonl": self._sid}
        busy = None
        async with self._http.get(f"{self._base}/stream/unified", params=params) as r:
            async for raw in _lines(r.content):
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    frame = json.loads(line[5:])
                except ValueError:
                    continue
                if frame.get("ch") == "jsonl" and isinstance(frame.get("ev"), dict):
                    yield frame["ev"]
                elif frame.get("ch") == "overview" and isinstance(frame.get("data"), dict):
                    tab = frame["data"].get(self._sid)
                    now = bool(tab.get("busy")) if isinstance(tab, dict) else False
                    if now != busy:
                        busy = now
                        yield {"type": "busy", "busy": now}


async def _lines(content: aiohttp.StreamReader) -> AsyncIterator[bytes]:
    """届いた順に 1 行ずつ返す (= 長さの上限なし。 最後に改行の無い残りは捨てる)。"""
    pending = bytearray()
    async for chunk in content.iter_any():
        pending += chunk
        start = 0
        while (end := pending.find(b"\n", start)) != -1:
            yield bytes(pending[start:end])
            start = end + 1
        del pending[:start]
