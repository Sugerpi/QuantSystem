"""唯讀 artifact 載入層（§11.1 行程邊界；§5.1）。

presentation 永不 import 引擎：只讀 runs/、snapshots/ 的 parquet/JSON。
由 tests/test_presentation/test_architecture.py 的 AST 守護強制此邊界。
"""

from __future__ import annotations

__all__: list[str] = []
