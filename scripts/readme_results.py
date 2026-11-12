"""Rewrite the README results table from outputs/valuations.json.

Usage: python -m scripts.readme_results  (or `make readme`)
"""

import json
import re
from pathlib import Path

from cac40val.config import load_companies
from cac40val.outputs.verdict import verdict

START = "<!-- RESULTS:START -->"
END = "<!-- RESULTS:END -->"
HEADER = [
    "Company",
    "Ticker",
    "Price €",
    "Bear / Base / Bull €",
    "Upside (base)",
    "WACC",
    "Verdict",
]


def _num(x: float | None, fmt: str) -> str:
    return "n/a" if x is None else format(x, fmt)


def render_table(valuations: list[dict], names: dict[str, str]) -> str:
    """Markdown table, one row per valuation (pure function, no I/O)."""
    lines = [
        "| " + " | ".join(HEADER) + " |",
        "|---|---|--:|--:|--:|--:|---|",
    ]
    for v in valuations:
        price = v.get("price")
        sc = v.get("scenarios", {})
        bear, base, bull = sc.get("bear"), sc.get("base"), sc.get("bull")
        upside = v.get("upside_base")
        verd = verdict(base, price) if base is not None and price else "n/a"
        cells = [
            names.get(v["ticker"], v["ticker"]),
            f"`{v['ticker']}`",
            _num(price, ",.2f"),
            f"{_num(bear, ',.0f')} / **{_num(base, ',.0f')}** / {_num(bull, ',.0f')}",
            _num(upside, "+.1%"),
            _num(v.get("wacc"), ".2%"),
            verd,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def replace_block(readme: str, table: str) -> str:
    """Replace everything between the RESULTS markers with ``table``."""
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(readme):
        raise ValueError(f"README has no {START} ... {END} block")
    return pattern.sub(lambda _: f"{START}\n{table}\n{END}", readme, count=1)


def main(
    readme: Path = Path("README.md"), valuations: Path = Path("outputs/valuations.json")
) -> None:
    data = json.loads(valuations.read_text(encoding="utf-8"))
    names = {c.ticker: c.name for c in load_companies()}
    readme.write_text(
        replace_block(readme.read_text(encoding="utf-8"), render_table(data, names)),
        encoding="utf-8",
    )
    print(f"Updated results table in {readme} ({len(data)} companies)")


if __name__ == "__main__":
    main()
