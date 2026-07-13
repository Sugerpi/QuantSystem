# QuantCore

美股 ETF 的量化配置研究系統：以**橫斷面動量**決定持有什麼、以 **GARCH/DCC 波動率模型**決定持有多少，全程 walk-forward、無 look-ahead、成本誠實。

- 規格唯一來源：[`DEVELOPMENT_GUIDE v1.2.md`](DEVELOPMENT_GUIDE%20v1.2.md)
- 開發守則：[`CLAUDE.md`](CLAUDE.md)
- 進度追蹤：[`PROGRESS.md`](PROGRESS.md)

## 開發環境（uv）

```bash
uv sync --extra dev      # 建立 .venv 並安裝依賴（含開發工具）
uv run pytest            # 跑測試
uv run ruff check .      # lint
uv run black --check .   # 格式檢查
```

## 現況

Phase 0（骨架）進行中。詳見 `PROGRESS.md`。
