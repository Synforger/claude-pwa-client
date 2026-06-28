"""observability layer: correlation / redact / structured_log / event_journal / metrics / inspector / replay。

W1 段階では correlation + redact の最小 stub のみ立てる。 本実装は W3。

scope (= W3 完成形):
    - correlation.py: ContextVar + W3C traceparent 互換 corr_id を全 layer に伝播
    - structured_log.py: structlog ベース JSONL writer (= ADR-012)
    - event_journal.py: 全 SSE / WS event を shadow 記録 (= rolling daily file)
    - metrics.py: queue size / reconnect / latency 集計、 /debug/metrics export
    - inspector.py: /debug/state 内容組立
    - replay.py: event_journal を時刻区間 + sid 指定で再配信
    - redact.py: sensitive field 自動 mask
"""
