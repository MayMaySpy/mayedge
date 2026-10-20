from __future__ import annotations

from fastapi import FastAPI

from mayedge.api.routes.account import router as account_router
from mayedge.api.routes.alerts import router as alerts_router
from mayedge.api.routes.algos import router as algos_router
from mayedge.api.routes.journal import router as journal_router
from mayedge.api.routes.kill import router as kill_router
from mayedge.api.routes.markets import router as markets_router
from mayedge.api.routes.orders import router as orders_router
from mayedge.api.routes.scan import router as scan_router


def include_api(app: FastAPI) -> None:
    app.include_router(alerts_router)
    app.include_router(scan_router)
    app.include_router(markets_router)
    app.include_router(account_router)
    app.include_router(journal_router)
    app.include_router(orders_router)
    app.include_router(algos_router)
    app.include_router(kill_router)
