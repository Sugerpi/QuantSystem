"""Run Lab job 狀態的原子寫入（規格 §2/§3.1）。純檔案操作、無引擎依賴。

status.json 由回測子行程權威擁有：每次 merge 傳入欄位 + 更新 heartbeat_at，
以 temp + os.replace 原子寫回（UI 讀到不會是半寫檔）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def write_status(status_file: str | Path, **fields) -> None:
    """讀現有 status.json（若有）→ merge fields → 更新 heartbeat_at → 原子寫回。"""
    path = Path(status_file)
    current: dict = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(fields)
    current["heartbeat_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
