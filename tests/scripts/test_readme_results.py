import pytest

from scripts.readme_results import END, START, render_table, replace_block

VALUATIONS = [
    {
        "ticker": "MC.PA",
        "price": 400.0,
        "scenarios": {"bear": 300.0, "base": 340.0, "bull": 420.0},
        "upside_base": -0.15,
        "wacc": 0.0984,
    },
    {
        "ticker": "XX.PA",
        "price": 100.0,
        "scenarios": {"bear": 95.0, "base": 120.0, "bull": 140.0},
        "upside_base": 0.20,
        "wacc": 0.08,
    },
]


def test_render_table_rows_and_verdicts():
    table = render_table(VALUATIONS, {"MC.PA": "LVMH"})
    lines = table.splitlines()
    assert lines[0].startswith("| Company | Ticker | Price €")
    assert len(lines) == 4
    assert lines[2] == (
        "| LVMH | `MC.PA` | 400.00 | 300 / **340** / 420 | -15.0% | 9.84% | Overvalued |"
    )
    # unknown name falls back to the ticker; base 20% above price -> undervalued
    assert lines[3].startswith("| XX.PA | `XX.PA` |")
    assert lines[3].endswith("| +20.0% | 8.00% | Undervalued |")


def test_render_table_missing_values():
    row = {"ticker": "KER.PA", "price": 10.0, "scenarios": {}, "upside_base": None, "wacc": None}
    line = render_table([row], {}).splitlines()[2]
    assert "n/a / **n/a** / n/a" in line
    assert line.endswith("| n/a | n/a | n/a |")


def test_replace_block():
    readme = f"intro\n{START}\nold\n{END}\noutro\n"
    out = replace_block(readme, "NEW")
    assert out == f"intro\n{START}\nNEW\n{END}\noutro\n"
    with pytest.raises(ValueError):
        replace_block("no markers", "NEW")
