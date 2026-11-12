from pathlib import Path

import pytest

from cac40val.ingest.rates import load_erp, parse_ecb_csv


def test_parse_ecb_csv_percent_to_decimal():
    df = parse_ecb_csv(Path("tests/fixtures/ecb_oat.csv").read_text())
    assert list(df.columns) == ["date", "rf_oat10y"]
    assert len(df) == 2  # empty observation dropped
    assert df.iloc[0]["rf_oat10y"] == pytest.approx(0.0312)
    assert str(df.iloc[0]["date"]) == "2024-01-01"


def test_load_erp_france():
    assert 0.03 <= load_erp() <= 0.10


def test_load_erp_empty_raises(tmp_path):
    p = tmp_path / "erp.csv"
    p.write_text("country,erp,source_date,source_url\nFrance,,,\n")
    with pytest.raises(ValueError, match="empty"):
        load_erp(p)


def test_load_erp_missing_country(tmp_path):
    p = tmp_path / "erp.csv"
    p.write_text("country,erp,source_date,source_url\nSpain,0.06,2026-01-01,u\n")
    with pytest.raises(ValueError, match="France"):
        load_erp(p)
