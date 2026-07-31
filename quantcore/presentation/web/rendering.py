"""頁面渲染：整頁 vs HTMX 片段。HX-Request → 只回內容片段（不含骨架）。

亦提供 controls_for：各頁共用的全域控制解析（run/策略/日期），避免每個路由重寫。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, controls
from quantcore.presentation.web.templating import templates


def controls_for(request: Request) -> controls.Controls:
    """由 request 的 runs_root + query params 組出全域 Controls（缺 runs 目錄回空）。"""
    root = request.app.state.runs_root
    runs = cache.read(root, readers.list_runs) if root.exists() else []
    return controls.parse_controls(request.query_params, root, runs)


NAV = [
    ("/overview", "總覽"),
    ("/decisions", "決策解剖"),
    ("/garch", "GARCH"),
    ("/correlation", "相關結構"),
    ("/portfolio", "組合與成本"),
    ("/ablation", "消融"),
    ("/data-quality", "資料品質"),
    ("/run-lab", "回測工作台"),
    ("/price-trades", "價格與交易"),
]


def render_page(
    request: Request,
    *,
    active: str,
    full_template: str,
    content_template: str,
    context: dict,
) -> HTMLResponse:
    base_ctx = {"nav": NAV, "active": active, **context}
    is_hx = request.headers.get("HX-Request") == "true"
    name = content_template if is_hx else full_template
    return templates.TemplateResponse(request, name, base_ctx)
