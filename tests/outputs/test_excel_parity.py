"""Excel/engine parity: evaluate the workbook's live formula chain and compare to the engine."""

import re
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from cac40val.outputs.excel import write_excel

ROOT = Path(__file__).resolve().parents[2]
_REF = re.compile(r"(?:(\w+)!)?\$?([A-Z]+)\$?(\d+)")
_SUM = re.compile(r"SUM\(([A-Z])(\d+):([A-Z])(\d+)\)")
TV_FORMULA = (
    "=(F4*(1+Assumptions!B12)*(Assumptions!F7*(1-Assumptions!B11)+Assumptions!B8"
    "-Assumptions!B9)-Assumptions!B10*F4*Assumptions!B12)/(WACC!B15-Assumptions!B12)"
)


def evaluate(wb, sheet: str, ref: str) -> float:
    """Recursively evaluate a cell holding +-*/^, parentheses, refs and same-row SUM ranges."""
    value = wb[sheet][ref].value
    if not (isinstance(value, str) and value.startswith("=")):
        return value

    def expand(m):
        c0, r0, c1, r1 = m.groups()
        assert r0 == r1, "only same-row ranges are supported"
        cols = [chr(c) for c in range(ord(c0), ord(c1) + 1)]
        return "(" + "+".join(f"{c}{r0}" for c in cols) + ")"

    expr = _SUM.sub(expand, value[1:]).replace("^", "**")

    def resolve(m):
        return f"({evaluate(wb, m.group(1) or sheet, m.group(2) + m.group(3))!r})"

    # eval is safe here: the expression only contains numbers and operators from our workbook.
    return eval(_REF.sub(resolve, expr))


def _assert_parity(path: Path, engine_base: float):
    wb = load_workbook(path)
    assert wb["DCF"]["B15"].value == TV_FORMULA
    assert wb["DCF"]["B9"].value == "=B8-Assumptions!$B$4*Assumptions!$B$10"
    assert evaluate(wb, "DCF", "B23") == pytest.approx(engine_base, rel=1e-9)
    assert evaluate(wb, "Summary", "B3") == pytest.approx(engine_base, rel=1e-9)


def test_excel_formulas_match_engine_fixture(valuation, tmp_path):
    _assert_parity(write_excel(valuation, tmp_path / "m.xlsx"), valuation.scenarios["base"])


def test_excel_formulas_match_engine_pipeline(tmp_path):
    from cac40val.pipeline import build_multiples, value_company
    from tests.test_pipeline import COMPANIES, SETTINGS, seed_db

    con = seed_db()
    mult = build_multiples(con, COMPANIES, pd.Timestamp("2026-11-10"))
    v = value_company(con, COMPANIES[0], SETTINGS, mult, None)
    _assert_parity(write_excel(v, tmp_path / "m.xlsx"), v.scenarios["base"])


def test_committed_mc_model_matches_its_engine_check():
    path = ROOT / "outputs" / "MC.PA" / "MC.PA_model.xlsx"
    if not path.exists():
        pytest.skip("committed model not generated")
    wb = load_workbook(path)
    _assert_parity(path, wb["Summary"]["B13"].value)


def test_workbook_recalculates_on_open(valuation, tmp_path):
    wb = load_workbook(write_excel(valuation, tmp_path / "m.xlsx"))
    assert wb.calculation.fullCalcOnLoad is True
