"""頁 5 組合與成本：權重堆疊面積、曝險軌跡+帶事件、換手+累積成本（§11.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    if ctrl.run_dir is None or not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = "此頁需回測 run（含 nav/weights/decisions）。"
    else:
        nav = cache.read(ctrl.run_dir / "nav.parquet", lambda p: readers.load_nav(p.parent))
        weights = cache.read(
            ctrl.run_dir / "weights.parquet", lambda p: readers.load_weights(p.parent)
        )
        decisions = cache.read(
            ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent)
        )
        strat = (ctrl.strategies or sorted(nav["strategy_id"].unique()))[0]
        ctx.update(
            strategy=strat,
            stack_fig=charts.to_fragment(charts.weight_stack(weights, strat), "pf-stack"),
            band_fig=charts.to_fragment(charts.exposure_band(decisions, strat), "pf-band"),
            cost_fig=charts.to_fragment(charts.turnover_cost(nav, strat), "pf-cost"),
        )
    return render_page(
        request,
        active="/portfolio",
        full_template="portfolio.html",
        content_template="portfolio_content.html",
        context=ctx,
    )
