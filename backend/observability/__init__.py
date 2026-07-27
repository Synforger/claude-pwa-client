"""observability layer: correlation / redact / metrics / inspector / server_timing。

structured_log / event_journal / replay は 2026-07-27 に退役 (= 記録ゼロのまま
維持されていた死蔵層、 backend の log は stdlib logging に統一済み)。

scope:
    - correlation.py: ContextVar + W3C traceparent 互換 corr_id を全 layer に伝播
    - metrics.py: queue size / reconnect / latency 集計、 /debug/metrics export
    - inspector.py: /debug/state 内容組立
    - redact.py: sensitive field 自動 mask
"""
