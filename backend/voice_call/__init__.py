"""電話の会話: iPhone の app と WebRTC でつなぎ、 声の会話を backend の中で回す (= Pipecat)。

画面の会話 (= `frontend/src/features/voice/`) は画面の中で声の区間と言い終えを判定する。 iPhone の app は、
画面が裏に回っても会話を続けるために、 マイクと声だけを持ち、 判定から先を全部ここに任せる。

Pipecat は追加で入れる部品 (= `uv sync --extra voice-call`)。 入っていなければ、 電話の口は
`voice_call_unavailable` を返す。
"""
