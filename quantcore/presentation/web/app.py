"""FastAPI app factory。掛靜態檔、模板、路由。啟動回測只走 subprocess（Run Lab，7b）。

不 import 引擎（§2.2）——只 import readers 與 web 子模組（jobs 只 subprocess 呼叫引擎 CLI）。
"""

from __future__ import annotations

import contextlib
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from quantcore.presentation import jobs
from quantcore.presentation.web.routes import (
    ablation,
    correlation,
    data_quality,
    decisions,
    garch,
    overview,
    portfolio,
    price_trades,
    run_lab,
)
from quantcore.presentation.web.templating import STATIC_DIR


def create_app(runs_root: Path | None = None, jobs_root: Path | None = None) -> FastAPI:
    rroot = Path(runs_root or os.environ.get("QUANTCORE_RUNS_ROOT", "runs"))
    jroot = Path(jobs_root or os.environ.get("QUANTCORE_JOBS_ROOT", "jobs"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()

        def _tick():
            while not stop.wait(3.0):
                # 心跳執行緒不因單次錯誤中止
                with contextlib.suppress(Exception):
                    jobs.reconcile_and_advance(jroot, rroot)

        t = threading.Thread(target=_tick, daemon=True)
        t.start()
        yield
        stop.set()

    app = FastAPI(title="QuantCore Dashboard", lifespan=lifespan)
    app.state.runs_root = rroot
    app.state.jobs_root = jroot
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(overview.router)
    app.include_router(decisions.router)
    app.include_router(garch.router)
    app.include_router(correlation.router)
    app.include_router(ablation.router)
    app.include_router(portfolio.router)
    app.include_router(data_quality.router)
    app.include_router(price_trades.router)
    app.include_router(run_lab.router)

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/overview")

    return app


app = create_app()
