"""Excel model: blue inputs, black formulas, linked Summary/DCF/WACC sheets."""

import math
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from cac40val.outputs.verdict import OVERVALUED_BELOW, UNDERVALUED_ABOVE

BLUE = Font(name="Calibri", size=10, color="000000FF")
BLACK = Font(name="Calibri", size=10, color="00000000")
BOLD = Font(name="Calibri", size=10, bold=True)
TITLE = Font(name="Calibri", size=14, bold=True, color="00FFFFFF")
HEADER = Font(name="Calibri", size=10, bold=True, color="00FFFFFF")
NAVY = PatternFill("solid", fgColor="001F3864")
GREY = PatternFill("solid", fgColor="00D9E1F2")

MN = "#,##0.0,,"  # raw EUR displayed in millions
PCT = "0.0%"
PS = "#,##0.00"
VERDICT_FORMULA = (
    f'=IF(B3>B4*{UNDERVALUED_ABOVE},"Undervalued",'
    f'IF(B3<B4*{OVERVALUED_BELOW},"Overvalued","Fairly valued"))'
)
YEARS = "BCDEF"
# Gordon TV on a normalised year-6 FCFF: Y5 revenue grown at g, Y5 EBIT margin, D&A/capex
# ratios, and the NWC investment growth at g needs (NWC% x Y5 revenue x g). Mirrors
# cac40val.valuation.dcf.normalized_terminal_fcff.
TV_FORMULA = (
    "=(F4*(1+Assumptions!B12)*(Assumptions!F7*(1-Assumptions!B11)+Assumptions!B8"
    "-Assumptions!B9)-Assumptions!B10*F4*Assumptions!B12)/(WACC!B15-Assumptions!B12)"
)


def _clean(x):
    if x is None:
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _put(ws, ref, value, fmt=None, font=BLACK):
    c = ws[ref]
    c.value = _clean(value)
    c.font = font
    if fmt:
        c.number_format = fmt
    return c


def _title(ws, text, width=7):
    ws["A1"].value = text
    for col in range(1, width + 1):
        ws.cell(1, col).fill = NAVY
    ws["A1"].font = TITLE
    ws.column_dimensions["A"].width = 38
    for col in range(2, width + 1):
        ws.column_dimensions[get_column_letter(col)].width = 15


def _header(ws, row, labels):
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row, i, label)
        c.font = HEADER
        c.fill = NAVY
        c.alignment = Alignment(horizontal="center" if i > 1 else "left")


def _frame(ws, df: pd.DataFrame, top: int, index_label: str, fmt, index_fmt=None):
    _header(ws, top, [index_label, *[str(c) for c in df.columns]])
    for r, (idx, row) in enumerate(df.iterrows(), start=top + 1):
        c = ws.cell(r, 1, idx)
        c.font = BOLD
        if index_fmt:
            c.number_format = index_fmt
        c.alignment = Alignment(horizontal="left")
        for j, val in enumerate(row, start=2):
            cell = ws.cell(r, j, _clean(None if pd.isna(val) else float(val)))
            cell.font = BLACK
            cell.number_format = fmt


def _assumptions(wb, v):
    ws = wb.create_sheet("Assumptions")
    _title(ws, f"{v.ticker} - Base case assumptions (blue = input)", 6)
    d = v.drivers["base"]
    _header(ws, 3, ["Driver", "Y1", "Y2", "Y3", "Y4", "Y5"])
    rows = [
        (4, "Last actual revenue (EUR m)", v.last_revenue, MN),
        (5, "Last actual NWC (memo, not used)", v.last_nwc, MN),
        (8, "D&A % revenue", d.da_pct, PCT),
        (9, "Capex % revenue", d.capex_pct, PCT),
        (10, "NWC % revenue", d.nwc_pct, PCT),
        (11, "Tax rate", d.tax_rate, PCT),
        (12, "Terminal growth", v.g, PCT),
        (13, "Net debt (EUR m)", v.net_debt, MN),
        (14, "Minorities (EUR m)", v.minorities, MN),
        (15, "Associates (EUR m)", v.associates, MN),
        (16, "Shares outstanding", v.shares, "#,##0"),
    ]
    for r, label, val, fmt in rows:
        ws.cell(r, 1, label).font = BOLD
        _put(ws, f"B{r}", val, fmt, BLUE)
    for r, label, series in (
        (6, "Revenue growth", d.revenue_growth),
        (7, "EBIT margin", d.ebit_margin),
    ):
        ws.cell(r, 1, label).font = BOLD
        for col, val in zip(YEARS, series, strict=True):
            _put(ws, f"{col}{r}", val, PCT, BLUE)
    ws["A18"].value = "Driver sources"
    ws["A18"].font = BOLD
    for i, (k, src) in enumerate(d.sources.items(), start=19):
        ws.cell(i, 1, k).font = BLACK
        ws.cell(i, 2, src).font = BLACK


def _wacc(wb, v):
    ws = wb.create_sheet("WACC")
    _title(ws, f"{v.ticker} - Cost of capital", 3)
    ws["B2"].value = "Value"
    ws["B2"].font = BOLD
    inputs = [
        (3, "Risk-free rate (OAT 10Y)", v.rf, "0.00%"),
        (4, "Beta (Blume-adjusted)", v.beta, "0.00"),
        (5, "Equity risk premium", v.erp, "0.00%"),
        (6, "Pre-tax cost of debt", v.kd, "0.00%"),
        (8, "Equity value, market cap (EUR m)", v.market_cap, MN),
        (9, "Debt value, gross debt (EUR m)", v.gross_debt, MN),
    ]
    for r, label, val, fmt in inputs:
        ws.cell(r, 1, label).font = BOLD
        _put(ws, f"B{r}", val, fmt, BLUE)
    ws["A7"].value = "Tax rate (linked to Assumptions)"
    ws["A7"].font = BOLD
    _put(ws, "B7", "=Assumptions!B11", PCT)
    calcs = [
        (11, "Cost of equity (rf + beta x ERP)", "=B3+B4*B5", "0.00%"),
        (12, "After-tax cost of debt", "=B6*(1-B7)", "0.00%"),
        (13, "Weight of equity", "=B8/(B8+B9)", PCT),
        (14, "Weight of debt", "=B9/(B8+B9)", PCT),
        (15, "WACC", "=B13*B11+B14*B12", "0.00%"),
    ]
    for r, label, f, fmt in calcs:
        ws.cell(r, 1, label).font = BOLD
        _put(ws, f"B{r}", f, fmt)
    ws["A15"].fill = GREY
    ws["B15"].fill = GREY
    ws["B15"].font = BOLD


def _dcf(wb, v):
    ws = wb.create_sheet("DCF")
    _title(ws, f"{v.ticker} - DCF, base case (EUR m)", 6)
    _header(ws, 2, ["", "Y1", "Y2", "Y3", "Y4", "Y5"])
    labels = {
        3: "Year",
        4: "Revenue",
        5: "EBIT",
        6: "D&A",
        7: "Capex",
        8: "NWC",
        9: "Change in NWC",
        10: "FCFF",
        11: "Discount factor",
        12: "PV of FCFF",
    }
    for r, label in labels.items():
        ws.cell(r, 1, label).font = BOLD
    for i, col in enumerate(YEARS):
        prev = YEARS[i - 1] if i else None
        _put(ws, f"{col}3", i + 1, "0")
        base_rev = "Assumptions!$B$4" if i == 0 else f"{prev}4"
        _put(ws, f"{col}4", f"={base_rev}*(1+Assumptions!{col}6)", MN)
        _put(ws, f"{col}5", f"={col}4*Assumptions!{col}7", MN)
        _put(ws, f"{col}6", f"={col}4*Assumptions!$B$8", MN)
        _put(ws, f"{col}7", f"={col}4*Assumptions!$B$9", MN)
        _put(ws, f"{col}8", f"={col}4*Assumptions!$B$10", MN)
        prev_nwc = "Assumptions!$B$4*Assumptions!$B$10" if i == 0 else f"{prev}8"
        _put(ws, f"{col}9", f"={col}8-{prev_nwc}", MN)
        _put(ws, f"{col}10", f"={col}5*(1-Assumptions!$B$11)+{col}6-{col}7-{col}9", MN)
        _put(ws, f"{col}11", f"=1/(1+WACC!$B$15)^{col}3", "0.0000")
        _put(ws, f"{col}12", f"={col}10*{col}11", MN)
    summary = [
        (14, "Sum of PV of FCFF", "=SUM(B12:F12)", MN),
        (15, "Terminal value (Gordon, normalised Y6 FCFF)", TV_FORMULA, MN),
        (16, "PV of terminal value", "=B15*F11", MN),
        (17, "Enterprise value", "=B14+B16", MN),
        (18, "Net debt", "=Assumptions!B13", MN),
        (19, "Minorities", "=Assumptions!B14", MN),
        (20, "Associates", "=Assumptions!B15", MN),
        (21, "Equity value", "=B17-B18-B19+B20", MN),
        (22, "Shares outstanding", "=Assumptions!B16", "#,##0"),
        (23, "Value per share (EUR)", "=B21/B22", PS),
    ]
    for r, label, f, fmt in summary:
        ws.cell(r, 1, label).font = BOLD
        _put(ws, f"B{r}", f, fmt)
    for ref in ("A17", "B17", "A23", "B23"):
        ws[ref].fill = GREY
    ws["B17"].font = BOLD
    ws["B23"].font = BOLD


def _sensitivity(wb, v):
    ws = wb.create_sheet("Sensitivity")
    _title(ws, f"{v.ticker} - Value per share: WACC (rows) x terminal growth (cols)", 6)
    ws["A2"].value = "Engine output (static values, not formulas)"
    ws["A2"].font = Font(name="Calibri", size=10, italic=True)
    df = v.sensitivity.copy()
    df.columns = [f"{c:.2%}" for c in df.columns]
    df.index = [f"{i:.2%}" for i in df.index]
    _frame(ws, df, 4, "WACC \\ g", PS)


def _comps(wb, v):
    ws = wb.create_sheet("Comps")
    _title(ws, f"{v.ticker} - Trading comparables (static)", 6)
    peers = v.peers
    cols = [
        c
        for c in ("ticker", "price_eur", "market_cap_eur", "ev_sales", "ev_ebitda", "pe")
        if c in peers.columns
    ]
    _header(ws, 3, cols)
    r = 4
    for _, row in peers[cols].iterrows():
        for j, c in enumerate(cols, start=1):
            val = row[c]
            cell = ws.cell(
                r, j, _clean(None if (not isinstance(val, str) and pd.isna(val)) else val)
            )
            cell.font = BLACK
            if c == "market_cap_eur":
                cell.number_format = MN
            elif c != "ticker":
                cell.number_format = "0.00"
        r += 1
    r += 1
    ws.cell(r, 1, "Implied value per share (EUR), peer IQR").font = BOLD
    _frame(ws, v.comps_implied, r + 1, "Multiple", PS)


def _historicals(wb, v):
    ws = wb.create_sheet("Historicals")
    _title(ws, f"{v.ticker} - Reported financials (EUR m, static)", 8)
    df = v.historicals.T
    df.columns = [int(c) for c in df.columns]
    _frame(ws, df, 3, "Line item", MN)
    for r in range(4, 4 + len(df)):
        if df.index[r - 4] == "shares_outstanding":
            for c in range(2, 2 + df.shape[1]):
                ws.cell(r, c).number_format = "#,##0"


def _summary(wb, v):
    ws = wb["Summary"]
    _title(ws, f"{v.ticker} - Valuation summary", 4)
    base_f = "=DCF!B23"
    rows = [
        (3, "Base value per share (EUR)", base_f, PS, BOLD),
        (4, "Current price (EUR)", v.price, PS, BLUE),
        (5, "Upside / (downside)", "=B3/B4-1", PCT, BOLD),
        (
            6,
            "Verdict",
            VERDICT_FORMULA,
            None,
            BOLD,
        ),
        (7, "WACC", "=WACC!B15", "0.00%", BLACK),
        (8, "Terminal growth", "=Assumptions!B12", "0.00%", BLACK),
        (9, "Enterprise value (EUR m)", "=DCF!B17", MN, BLACK),
        (11, "Bear value per share (engine)", v.scenarios["bear"], PS, BLACK),
        (12, "Bull value per share (engine)", v.scenarios["bull"], PS, BLACK),
        (13, "Engine check (static, base per share)", v.scenarios["base"], PS, BLACK),
    ]
    for r, label, val, fmt, font in rows:
        ws.cell(r, 1, label).font = BOLD
        _put(ws, f"B{r}", val, fmt, font)
    ws["B3"].fill = GREY
    ws["C13"].value = "Formula result in B3 must equal this within rounding"
    ws["C13"].font = Font(name="Calibri", size=9, italic=True)
    ws["A15"].value = "Driver sources"
    ws["A15"].font = BOLD
    _header(ws, 16, ["Driver", "Source"])
    for i, (k, src) in enumerate(v.drivers["base"].sources.items(), start=17):
        ws.cell(i, 1, k).font = BLACK
        ws.cell(i, 2, src).font = BLACK


def write_excel(v, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.active.title = "Summary"
    _assumptions(wb, v)
    _historicals(wb, v)
    _dcf(wb, v)
    _wacc(wb, v)
    _sensitivity(wb, v)
    _comps(wb, v)
    _summary(wb, v)
    # openpyxl stores formulas without cached results: force Excel/LibreOffice to recalculate
    # on open so viewers never see empty cells.
    wb.calculation.fullCalcOnLoad = True
    wb.save(path)
    return path
