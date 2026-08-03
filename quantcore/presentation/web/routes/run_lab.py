"""頁 8 回測工作台（Run Lab，§5）：YAML 編輯器、驗證、提交、job 清單輪詢。

啟動回測只以 subprocess（jobs.py）；不 import 引擎。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import jobs
from quantcore.presentation.web.rendering import controls_for, render_page
from quantcore.presentation.web.templating import templates

router = APIRouter()

_CONFIG_DIR = Path("quantcore/config")


def _base_configs() -> list[str]:
    if not _CONFIG_DIR.exists():
        return []
    return sorted(p.stem for p in _CONFIG_DIR.glob("*.yaml"))


def _jobs_root(request: Request) -> Path:
    return Path(request.app.state.jobs_root)


@router.get("/run-lab", response_class=HTMLResponse)
def run_lab(request: Request) -> HTMLResponse:
    base = request.query_params.get("base")
    yaml_text = ""
    if base and base in _base_configs():
        yaml_text = (_CONFIG_DIR / f"{base}.yaml").read_text(encoding="utf-8")
    ctx = {
        "ctrl": controls_for(request),
        "base_configs": _base_configs(),
        "selected_base": base or "",
        "yaml_text": yaml_text,
        "jobs": jobs.list_jobs(_jobs_root(request)),
    }
    return render_page(
        request,
        active="/run-lab",
        full_template="run_lab.html",
        content_template="run_lab_content.html",
        context=ctx,
    )


@router.post("/run-lab/validate", response_class=HTMLResponse)
def validate(request: Request, config_yaml: str = Form(...)) -> HTMLResponse:
    ok, msg = jobs.validate(config_yaml)
    return templates.TemplateResponse(request, "_validate_result.html", {"ok": ok, "msg": msg})


@router.post("/run-lab/submit", response_class=HTMLResponse)
def submit(
    request: Request, label: str = Form("run"), config_yaml: str = Form(...)
) -> HTMLResponse:
    jobs.submit(_jobs_root(request), label, config_yaml)
    return templates.TemplateResponse(
        request, "_job_list.html", {"jobs": jobs.list_jobs(_jobs_root(request))}
    )


@router.get("/run-lab/status", response_class=HTMLResponse)
def status(request: Request) -> HTMLResponse:
    jobs.reconcile_and_advance(_jobs_root(request), request.app.state.runs_root)
    return templates.TemplateResponse(
        request, "_job_list.html", {"jobs": jobs.list_jobs(_jobs_root(request))}
    )
