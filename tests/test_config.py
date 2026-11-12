from cac40val.config import load_companies, load_overrides, load_settings

TARGETS = ["MC.PA", "RMS.PA", "KER.PA", "OR.PA", "EL.PA"]
PEERS = ["CFR.SW", "MONC.MI", "1913.HK", "BC.MI"]


def test_companies_has_5_targets_and_4_peers():
    companies = load_companies()
    assert len(companies) == 9
    assert sum(c.is_target for c in companies) == 5
    assert [c.ticker for c in companies if c.is_target] == TARGETS
    assert [c.ticker for c in companies if not c.is_target] == PEERS


def test_settings_defaults():
    s = load_settings()
    assert s.tax_rate == 0.258
    assert s.terminal_growth == 0.02
    assert s.llm_model == "claude-sonnet-5-5"
    assert s.rf_override is None
    assert s.erp_override is None


def test_settings_benchmark_ticker():
    assert load_settings().benchmark_ticker == "^STOXX50E"


def test_overrides_missing_file_returns_empty(tmp_path):
    assert load_overrides("XXX", tmp_path) == {}


def test_overrides_reads_yaml(tmp_path):
    (tmp_path / "MC.PA.yaml").write_text("wacc: 0.08\n")
    assert load_overrides("MC.PA", tmp_path) == {"wacc": 0.08}
