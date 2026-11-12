from openpyxl import load_workbook

from cac40val.outputs.excel import write_excel


def test_excel_sheets_and_formulas(valuation, tmp_path):
    path = write_excel(valuation, tmp_path / "m.xlsx")
    wb = load_workbook(path)
    assert wb.sheetnames == [
        "Summary",
        "Assumptions",
        "Historicals",
        "DCF",
        "WACC",
        "Sensitivity",
        "Comps",
    ]
    assert wb["DCF"]["B17"].data_type == "f"
    assert wb["WACC"]["B15"].data_type == "f"
    assert wb["Assumptions"]["B6"].font.color.rgb.endswith("0000FF")


def test_excel_engine_check_cell(valuation, tmp_path):
    wb = load_workbook(write_excel(valuation, tmp_path / "m.xlsx"))
    ws = wb["Summary"]
    labels = {c.value: ws.cell(c.row, c.column + 1).value for row in ws.iter_rows() for c in row}
    assert labels["Engine check (static, base per share)"] == valuation.scenarios["base"]
    assert str(labels["Base value per share (EUR)"]).startswith("=DCF!")


def test_excel_year1_delta_nwc_uses_driver_basis(valuation, tmp_path):
    wb = load_workbook(write_excel(valuation, tmp_path / "m.xlsx"))
    assert wb["DCF"]["B9"].value == "=B8-Assumptions!$B$4*Assumptions!$B$10"
    assert wb["DCF"]["C9"].value == "=C8-B8"
    assert "memo" in wb["Assumptions"]["A5"].value
