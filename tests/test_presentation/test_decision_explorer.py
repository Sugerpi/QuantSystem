"""Decision Explorer 六層抽取 = AC① 自動化：抽取須逐層對上獨立解析的原始 decisions 列。"""

import json

import pandas as pd

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
