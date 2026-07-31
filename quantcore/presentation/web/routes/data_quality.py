"""頁 7 資料品質：快照 MANIFEST、資料源、overrides 裁決、tickers（§11.2）。

快照可能只有 hash 進版控、parquet 不在本機 → 優雅提示。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


@router.get("/data-quality", response_class=HTMLResponse)
def data_quality(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    if ctrl.run_dir is None:
        ctx["error"] = "runs/ 下無 run。"
    else:
        snap_dir = readers.snapshot_dir_for_run(ctrl.run_dir)
        if not snap_dir.exists():
            ctx["error"] = f"快照 {snap_dir} 不在本機（可能只有 hash 進版控）。"
        else:
            meta = cache.read(
                snap_dir / "metadata.json", lambda p: readers.load_snapshot_metadata(p.parent)
            )
            manifest = cache.read(
                snap_dir / "MANIFEST.json", lambda p: readers.load_snapshot_manifest(p.parent)
            )
            ctx.update(
                manifest_json=json.dumps(manifest, indent=2, ensure_ascii=False),
                sources_json=json.dumps(meta.get("sources", {}), indent=2, ensure_ascii=False),
                overrides=meta.get("overrides", []),
                tickers_json=json.dumps(meta.get("tickers", {}), indent=2, ensure_ascii=False),
            )
    return render_page(
        request,
        active="/data-quality",
        full_template="data_quality.html",
        content_template="data_quality_content.html",
        context=ctx,
    )
