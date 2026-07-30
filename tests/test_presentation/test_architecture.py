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


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _all_py() -> list[Path]:
    return [p for p in _PRESENTATION.rglob("*.py")]


def test_presentation_never_imports_engine():
    offenders = {}
    for path in _all_py():
        bad = {
            m
            for m in _imported_modules(path)
            if any(m == pre or m.startswith(pre + ".") for pre in _FORBIDDEN_PREFIXES)
        }
        if bad:
            offenders[str(path.relative_to(_PRESENTATION))] = sorted(bad)
    assert not offenders, f"presentation 違規 import 引擎：{offenders}"


def test_guard_has_teeth():
    """對一段含違規 import 的合成程式碼，守護邏輯必須抓到（否則守護是空殼）。"""
    import ast as _ast

    src = "from quantcore.backtest.engine import run_strategy\n"
    mods = {n.module for n in _ast.walk(_ast.parse(src)) if isinstance(n, _ast.ImportFrom)}
    assert any(m.startswith("quantcore.backtest") for m in mods)
