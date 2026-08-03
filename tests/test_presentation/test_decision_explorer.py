"""Decision Explorer 六層抽取 = AC① 自動化：抽取須逐層對上獨立解析的原始 decisions 列。"""

import json

import pandas as pd
import pytest

from quantcore.presentation import readers


def _raw_row(run_dir, strategy_id, decision_date):
    dec = pd.read_parquet(run_dir / "decisions.parquet")
    m = (dec["strategy_id"] == strategy_id) & (dec["decision_date"] == decision_date)
    return dec[m].iloc[0]


def test_six_layers_match_raw_decisions(run_dir):
    dec = readers.load_decisions(run_dir)
    full = dec[(dec["strategy_id"] == "full") & (dec["selected"].map(bool))].iloc[0]
    sid, ddate = full["strategy_id"], full["decision_date"]

    layers = readers.decision_layers(run_dir, sid, ddate)
    raw = _raw_row(run_dir, sid, ddate)

    # 非六層欄位：execution_date、event 也交叉核對
    assert raw["execution_date"] is not pd.NaT  # 挑到的列須有真實執行日，null 路徑另有專測
    assert layers.execution_date == pd.Timestamp(raw["execution_date"])
    assert layers.event == raw["event"]
    # (a) eligible  (b) momentum_scores + selected  (c) absmom
    assert layers.eligible == json.loads(raw["eligible"])
    assert layers.momentum_scores == json.loads(raw["momentum_scores"])
    assert layers.selected == json.loads(raw["selected"])
    assert layers.absmom == json.loads(raw["absmom"])
    # (d) sigma_hat（年化純量 dict）
    assert layers.sigma_hat == json.loads(raw["sigma_hat"])
    # (e) 曝險公式各項
    assert layers.w_risky == json.loads(raw["w_risky"])
    assert layers.sigma_p == raw["sigma_p"]
    assert layers.exposure_raw == raw["exposure_raw"]
    assert layers.exposure_applied == raw["exposure_applied"]
    assert bool(layers.band_blocked) == bool(raw["band_blocked"])
    # (f) 目標權重（含 CASH）
    assert layers.target_weights == json.loads(raw["target_weights"])


def test_decision_layers_missing_returns_none(run_dir):
    assert readers.decision_layers(run_dir, "full", pd.Timestamp("1990-01-01")) is None


def test_decision_layers_raises_on_duplicate_rows(tmp_path):
    """(strategy_id, decision_date) 理應唯一；出現重複列須 fail loud 而非靜默取第一列。"""
    ddate = pd.Timestamp("2020-01-02")
    row = {
        "strategy_id": "full",
        "decision_date": ddate,
        "execution_date": pd.NaT,
        "event": "selection",
        "eligible": json.dumps(["SPY"]),
        "momentum_scores": json.dumps({"SPY": 0.1}),
        "selected": json.dumps(["SPY"]),
        "absmom": json.dumps({"SPY": True}),
        "sigma_hat": json.dumps({"SPY": 0.2}),
        "w_risky": json.dumps({"SPY": 1.0}),
        "sigma_p": 0.2,
        "exposure_raw": 1.0,
        "exposure_applied": 1.0,
        "band_blocked": False,
        "target_weights": json.dumps({"SPY": 1.0, "CASH": 0.0}),
    }
    dec = pd.DataFrame([row, row])
    dec.to_parquet(tmp_path / "decisions.parquet")

    with pytest.raises(ValueError, match="有 2 列"):
        readers.decision_layers(tmp_path, "full", ddate)


def test_decision_layers_null_path_execution_date(run_dir):
    """band_blocked=True 的曝險檢查列（僅記錄、未執行）：execution_date 應為 None。"""
    dec = pd.read_parquet(run_dir / "decisions.parquet")
    blocked = dec[dec["band_blocked"] == True]  # noqa: E712
    if blocked.empty:
        pytest.skip("fixture 未觸發任何 band_blocked 列（80 天合成資料未產生曝險攔截）")

    row = blocked.iloc[0]
    layers = readers.decision_layers(run_dir, row["strategy_id"], row["decision_date"])

    assert layers.execution_date is None
    assert layers.band_blocked is True
