"""FastAPI app factory。掛靜態檔、模板、路由。啟動回測只走 subprocess（Run Lab，7b）。

不 import 引擎（§2.2）——只 import readers 與 web 子模組。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from quantcore.presentation.web.routes import overview, portfolio, stubs
from quantcore.presentation.web.templating import STATIC_DIR


def create_app(runs_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="QuantCore Dashboard")
    root = runs_root or Path(os.environ.get("QUANTCORE_RUNS_ROOT", "runs"))
    app.state.runs_root = Path(root)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(overview.router)
    app.include_router(portfolio.router)
    app.include_router(stubs.router)

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/overview")

    return app


app = create_app()
