"""旧 chat_routes 集約点 (= backend-F-28 / crosscut-F-04 で 3 分割した後の互換 shim)。

旧 585 行の `backend.routes.chat` には CRUD + フォーク + restart + 全 sid SSE +
views/ws + agents / accounts list がすべて入っていたが、 責務別に
`routes/sessions.py` / `routes/overview.py` / `routes/accounts.py` に分割した。

互換性 invariants (= 既存 test + 既存 import 経路は素通りで動く):
- `from backend.routes.chat import router` は 3 router を 1 つに include した
  集約 router を返す (= main.py からの単一 include が変わらない)。 main.py 側で
  3 router を個別 include する形にも段階移行可能だが、 まずは 1 router で互換維持。
- `chat_routes.fork_session(...)` / `chat_routes.delete_session(...)` /
  `chat_routes.restart_session(...)` / `chat_routes.require_session(...)` /
  `chat_routes._mark_user_stopped(...)` / `chat_routes._build_sessions_overview()`
  などの直接呼び出し test は、 ここで re-export してそのまま素通させる。
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.routes.accounts import (
    list_accounts,
    list_agents,
    router as _accounts_router,
)
from backend.routes.overview import (
    _build_all_status,
    _build_sessions_overview,
    _mark_user_stopped,
    all_status_stream,
    mark_session_seen,
    router as _overview_router,
    sessions_overview_stream,
    views_ws,
)
from backend.routes.sessions import (
    create_session,
    delete_session,
    fork_session,
    list_sessions,
    patch_session,
    require_session,
    restart_session,
    router as _sessions_router,
)

__all__ = [
    "router",
    "require_session",
    "list_sessions",
    "create_session",
    "patch_session",
    "fork_session",
    "restart_session",
    "delete_session",
    "list_agents",
    "list_accounts",
    "all_status_stream",
    "sessions_overview_stream",
    "mark_session_seen",
    "views_ws",
    "_build_all_status",
    "_build_sessions_overview",
    "_mark_user_stopped",
]

# 集約 router: main.py から `include_router(chat_routes.router)` 1 行で
# 旧来全 endpoint を受け取れる互換維持。 main.py を「3 router を個別 include する」
# 形に書き換えるのは段階移行で可能 (= 副 path consumer の rewire と独立で安全)。
router = APIRouter()
router.include_router(_sessions_router)
router.include_router(_overview_router)
router.include_router(_accounts_router)
