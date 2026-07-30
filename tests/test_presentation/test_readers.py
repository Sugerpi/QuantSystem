from quantcore.presentation import readers


def test_load_nav_weights(run_dir):
    nav = readers.load_nav(run_dir)
    assert {"date", "strategy_id", "nav", "turnover", "cost"} <= set(nav.columns)
    w = readers.load_weights(run_dir)
    assert {"date", "strategy_id", "ticker", "weight"} <= set(w.columns)


def test_load_trades_present(run_dir):
    tr = readers.load_trades(run_dir)
    assert tr is not None
    assert {"execution_date", "strategy_id", "ticker", "delta_weight", "cost"} <= set(tr.columns)


def test_load_trades_absent_returns_none(tmp_path):
    (tmp_path / "nav.parquet").write_bytes(b"")  # 任意檔，確保目錄存在
    assert readers.load_trades(tmp_path) is None


def test_load_metrics_and_manifest(run_dir):
    m = readers.load_metrics(run_dir)
    assert "full" in m and "sharpe" in m["full"]
    mf = readers.load_manifest(run_dir)
    assert set(mf) == {"identity", "content_hashes", "created_at"}


def test_load_config(run_dir):
    c = readers.load_run_config(run_dir)
    assert c["risk"]["corr_model"] == "ewma"


def test_load_decisions_parses_json_columns(run_dir):
    dec = readers.load_decisions(run_dir)
    # full 策略某決策列
    full = dec[dec["strategy_id"] == "full"].iloc[0]
    assert isinstance(full["target_weights"], dict)
    assert isinstance(full["eligible"], list)
    assert isinstance(full["selected"], list)
    # None 字面欄（如 bh_spy 的 momentum_scores）→ Python None
    bh = dec[dec["strategy_id"] == "bh_spy"].iloc[0]
    assert bh["momentum_scores"] is None
    # nullable boolean 保持
    assert dec["band_blocked"].dtype.name == "boolean"
    assert "corr_fell_back" in dec.columns
