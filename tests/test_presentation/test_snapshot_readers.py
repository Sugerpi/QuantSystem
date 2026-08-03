"""快照讀取器（頁 7 資料品質、頁 9 價格）。以合成快照結構測試，CI 可跑。"""

import json

import numpy as np

from quantcore.presentation import readers
from tests.fixtures.synthetic import make_dates, make_snapshot


def _write_snapshot(root, sid="synthetic_01"):
    d = root / sid
    d.mkdir(parents=True)
    dates = make_dates(30)
    rng = np.random.default_rng(0)
    snap = make_snapshot({"SPY": list(100.0 * np.cumprod(1 + rng.normal(0, 0.01, 30)))}, dates)
    snap["prices"].to_parquet(d / "prices.parquet", index=False)
    (d / "metadata.json").write_text(json.dumps({"overrides": []}), encoding="utf-8")
    (d / "MANIFEST.json").write_text(json.dumps({"snapshot_id": sid}), encoding="utf-8")
    return d


def test_load_adj_close_panel(tmp_path):
    d = _write_snapshot(tmp_path)
    panel = readers.load_adj_close_panel(d)
    assert "SPY" in panel.columns
    assert panel.index.name == "date"
    assert panel["SPY"].notna().all()


def test_load_snapshot_metadata_and_manifest(tmp_path):
    d = _write_snapshot(tmp_path)
    meta = readers.load_snapshot_metadata(d)
    assert "overrides" in meta
    man = readers.load_snapshot_manifest(d)
    assert man["snapshot_id"] == "synthetic_01"
