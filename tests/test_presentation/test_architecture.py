"""架構守護：presentation 永不 import 引擎模組（§2.2 行程邊界紅綠燈化）。"""

import ast
from pathlib import Path

_PRESENTATION = Path(__file__).resolve().parents[2] / "quantcore" / "presentation"
_FORBIDDEN_PREFIXES = (
    "quantcore.backtest",
    "quantcore.models",
    "quantcore.signals",
    "quantcore.portfolio",
    "quantcore.experiments",
    "quantcore.data",
    "quantcore.config",
)


def _imported_modules(source: str) -> set[str]:
    """收集一段原始碼所有被 import 的模組全名。

    ImportFrom 除了 module 本身，也展開 `from PKG import NAME` 為 `PKG.NAME`——
    否則 `from quantcore import backtest`（module='quantcore'）會漏掉 quantcore.backtest。
    """
    tree = ast.parse(source)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def _engine_offenders(source: str) -> set[str]:
    """回傳 source 中違規（import 引擎模組）的模組全名集合。"""
    return {
        m
        for m in _imported_modules(source)
        if any(m == pre or m.startswith(pre + ".") for pre in _FORBIDDEN_PREFIXES)
    }


def test_presentation_never_imports_engine():
    offenders = {}
    for path in _PRESENTATION.rglob("*.py"):
        bad = _engine_offenders(path.read_text(encoding="utf-8"))
        if bad:
            offenders[str(path.relative_to(_PRESENTATION))] = sorted(bad)
    assert not offenders, f"presentation 違規 import 引擎：{offenders}"


def test_guard_has_teeth_direct_import():
    """守護必須抓到 `from quantcore.backtest.engine import ...` —— 走真實偵測碼。"""
    src = "from quantcore.backtest.engine import run_strategy\n"
    assert "quantcore.backtest.engine" in _engine_offenders(src)


def test_guard_has_teeth_submodule_import():
    """守護必須抓到 `from quantcore import backtest`（曾漏掉的 bypass）—— 走真實偵測碼。"""
    src = "from quantcore import backtest\n"
    assert "quantcore.backtest" in _engine_offenders(src)


def test_guard_allows_stdlib_and_pandas():
    """合法 import 不得被誤判。"""
    src = "import json\nimport pandas as pd\nfrom pathlib import Path\n"
    assert _engine_offenders(src) == set()
