"""頁 1 總覽：KPI 卡片（本計畫只做卡片；NAV/回撤/曝險圖屬計畫 2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    metrics_by_strategy: dict[str, dict] = {}
    if ctrl.run_dir is not None and (ctrl.run_dir / "metrics.json").exists():
        all_metrics = cache.read(
            ctrl.run_dir / "metrics.json", lambda p: readers.load_metrics(p.parent)
        )
        for sid in ctrl.strategies:
            m = all_metrics.get(sid, {})
            metrics_by_strategy[sid] = {
                k: v for k, v in m.items() if isinstance(v, int | float) and not isinstance(v, bool)
            }
    return render_page(
        request,
        active="/overview",
        full_template="overview.html",
        content_template="overview_content.html",
        context={"ctrl": ctrl, "metrics_by_strategy": metrics_by_strategy},
    )
