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


def test_load_correlation_and_residuals(run_dir):
    corr = readers.load_correlation(run_dir)
    assert corr is not None
    assert {"decision_date", "strategy_id", "ticker_i", "ticker_j", "corr"} <= set(corr.columns)
    assert set(corr["strategy_id"].unique()) <= {"full", "full_erc"}
    resid = readers.load_residuals(run_dir)
    assert resid is not None
    assert {"strategy_id", "ticker", "date", "std_resid"} <= set(resid.columns)


def test_model_details_absent_returns_none(tmp_path):
    assert readers.load_correlation(tmp_path) is None
    assert readers.load_residuals(tmp_path) is None


def test_correlation_matrix_at_reshapes_long_to_square(run_dir):
    corr = readers.load_correlation(run_dir)
    d0 = corr["decision_date"].iloc[0]
    mat = readers.correlation_matrix_at(corr, "full", d0)
    assert mat.index.tolist() == mat.columns.tolist()  # 方陣、對稱標籤
    assert (mat.values.diagonal() == 1.0).all() or abs(mat.values.diagonal() - 1.0).max() < 1e-9


def test_list_runs_discovers_and_reads_identity(run_dir):
    runs_root = run_dir.parent
    runs = readers.list_runs(runs_root)
    names = [r["name"] for r in runs]
    assert run_dir.name in names
    entry = next(r for r in runs if r["name"] == run_dir.name)
    assert "created_at" in entry and "snapshot_id" in entry and "strategies" in entry
    assert "full" in entry["strategies"]


def test_list_runs_skips_non_run_dirs(tmp_path):
    (tmp_path / "not_a_run").mkdir()
    assert readers.list_runs(tmp_path) == []


def test_correlation_matrix_at_empty_when_no_rows(run_dir):
    corr = readers.load_correlation(run_dir)
    import pandas as pd

    mat = readers.correlation_matrix_at(corr, "full", pd.Timestamp("1990-01-01"))
    assert mat.empty


def test_list_runs_manifest_without_metrics_gives_empty_strategies(tmp_path):
    import json

    d = tmp_path / "run_x"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"identity": {"snapshot_id": "s1", "git_commit": "abc"}, "created_at": "t"}),
        encoding="utf-8",
    )
    runs = readers.list_runs(tmp_path)
    entry = next(r for r in runs if r["name"] == "run_x")
    assert entry["strategies"] == []
    assert entry["snapshot_id"] == "s1"


def test_load_comparison_bootstrap_absent_returns_none(tmp_path):
    assert readers.load_comparison(tmp_path) is None
    assert readers.load_bootstrap(tmp_path) is None
    assert readers.load_vol_eval(tmp_path) is None


def test_snapshot_dir_for_run(run_dir):
    from pathlib import Path

    cfg = readers.load_run_config(run_dir)
    got = readers.snapshot_dir_for_run(run_dir)
    assert isinstance(got, Path)
    assert got == Path(cfg["snapshot"])  # Path==Path 跨平台一致（str(Path) 在 Windows 為反斜線）
