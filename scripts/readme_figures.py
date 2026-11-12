"""Generate the README images from the committed data snapshot and one-pager PDF.

Usage: python -m scripts.readme_figures  (or `make figures`)
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from cac40val.config import load_companies, load_settings
from cac40val.pipeline import build_multiples, load_snapshot, valuation_date, value_company

OUT = Path("docs/img")
FOOTBALL_TICKERS = ["MC.PA", "RMS.PA"]
ONEPAGER_TICKER = "MC.PA"
NAVY, GREY, RED = "#1F3864", "#595959", "#C00000"


def football_png(v, name: str, path: Path) -> Path:
    fb = v.football
    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=150)
    for i, (_, r) in enumerate(fb.iterrows()):
        ax.barh(i, r["high"] - r["low"], left=r["low"], color=NAVY, alpha=0.85, height=0.5)
        for x, ha, dx in ((r["low"], "right", -4), (r["high"], "left", 4)):
            ax.annotate(
                f"{x:,.0f}",
                xy=(x, i),
                xytext=(dx, 0),
                textcoords="offset points",
                ha=ha,
                va="center",
                fontsize=8,
                color=GREY,
            )
    ax.axvline(v.price, color=RED, linestyle="--", linewidth=1.5)
    ax.annotate(
        f"Price {v.price:,.2f}",
        xy=(v.price, 1.0),
        xycoords=ax.get_xaxis_transform(),
        xytext=(0, 3),
        textcoords="offset points",
        color=RED,
        fontsize=9,
        ha="center",
        va="bottom",
    )
    ax.set_yticks(range(len(fb)), list(fb.index), fontsize=9)
    lo, hi = min(fb["low"].min(), v.price), max(fb["high"].max(), v.price)
    pad = 0.12 * (hi - lo)
    ax.set_xlim(lo - pad, hi + pad)
    ax.invert_yaxis()
    ax.set_xlabel("EUR per share", fontsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_title(
        f"{name} ({v.ticker}) — football field", loc="left", pad=20, fontsize=11, color=NAVY
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def onepager_png(pdf: Path, path: Path, zoom: float = 1.3) -> Path:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(path)
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con, settings = load_snapshot(), load_settings()
    companies = load_companies()
    multiples = build_multiples(con, companies, valuation_date(con, settings))
    by_ticker = {c.ticker: c for c in companies}
    for t in FOOTBALL_TICKERS:
        c = by_ticker[t]
        v = value_company(con, c, settings, multiples, None)
        print(football_png(v, c.name, OUT / f"football_field_{t.split('.')[0]}.png"))
    pdf = Path("outputs") / ONEPAGER_TICKER / f"{ONEPAGER_TICKER}_onepager.pdf"
    print(onepager_png(pdf, OUT / f"onepager_{ONEPAGER_TICKER.split('.')[0]}.png"))


if __name__ == "__main__":
    main()
