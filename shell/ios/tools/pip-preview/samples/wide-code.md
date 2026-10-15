直すのはこの 2 行。

```python
async def send_interruption(session_id: str, text: str, *, reason: str = "speech-started") -> dict[str, object]:
    return await client.post(f"/voice/interruption?sid={session_id}", json={"text": text, "reason": reason})
```
