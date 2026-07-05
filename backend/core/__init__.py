"""機能横断ユーティリティ層 (= fork / maintenance / push / usage)。

名前に反して「中枢データモデル」 はここではなく root の `backend/state.py` にある
(= SessionDef / AgentStatus / broadcaster 群、 fan-in 最大の module)。 core/ は
state / jsonl / terminal の上に乗る横断機能の置き場:

    - fork.py        — 会話 fork (= transcript 切り出し + resume 起動)
    - maintenance.py — 定期 GC / 掃除 loop
    - push.py        — Web Push (VAPID) 配信 + subscription 管理
    - usage.py       — rate-limit / usage 集計

新しい「どの層にも属さない機能」 はまずここが候補、 データモデルの追加は state.py へ。
"""
