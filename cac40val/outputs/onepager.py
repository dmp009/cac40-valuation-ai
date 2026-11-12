"""Single-page A4 PDF one-pager (matplotlib)."""

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from cac40val.outputs.verdict import verdict

__all__ = ["verdict", "write_onepager"]

NAVY, GREY, RED, GREEN, AMBER = "#1F3864", "#595959", "#C00000", "#2E7D32", "#B26A00"
VERDICT_COLOR = {"Undervalued": GREEN, "Overvalued": RED, "Fairly valued": AMBER}
DISCLAIMER = "Educational project, not investment advice"


def _wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width)) or ""


def _header(fig, v):
    fig.patches.append(
        plt.Rectangle((0, 0.94), 1, 0.06, transform=fig.transFigure, color=NAVY, zorder=0)
    )
    fig.text(
        0.05,
        0.965,
        f"{v.ticker}  |  Equity valuation one-pager",
        color="white",
        fontsize=15,
        fontweight="bold",
        va="center",
    )
    fig.text(0.95, 0.965, "DCF + trading comps", color="white", fontsize=9, ha="right", va="center")


def _metrics(fig, v):
    base = v.scenarios["base"]
    upside = base / v.price - 1
    rows = [
        ["Current price (EUR)", f"{v.price:,.2f}"],
        ["Base value / share (EUR)", f"{base:,.2f}"],
        ["Bear / bull (EUR)", f"{v.scenarios['bear']:,.2f} / {v.scenarios['bull']:,.2f}"],
        ["Upside to base", f"{upside:+.1%}"],
        ["WACC / terminal growth", f"{v.wacc:.2%} / {v.g:.2%}"],
        ["Enterprise value (EUR bn)", f"{v.ev_base / 1e9:,.1f}"],
        [
            "Gordon TV vs exit-multiple TV",
            "n/a"
            if v.tv_gordon_vs_exit_gap != v.tv_gordon_vs_exit_gap
            else f"{v.tv_gordon_vs_exit_gap:+.0%}",
        ],
    ]
    ax = fig.add_axes([0.05, 0.69, 0.9, 0.22])
    ax.axis("off")
    ax.set_title("Key metrics", loc="left", fontsize=10, fontweight="bold", color=NAVY)
    tbl = ax.table(cellText=rows, colWidths=[0.6, 0.4], loc="upper left", cellLoc="left")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.35)
    for cell in tbl.get_celld().values():
        cell.set_edgecolor("#D9D9D9")


def _football(fig, v):
    ax = fig.add_axes([0.22, 0.43, 0.7, 0.19])
    fb = v.football
    labels = list(fb.index)
    for i, (_, r) in enumerate(fb.iterrows()):
        ax.barh(i, r["high"] - r["low"], left=r["low"], color=NAVY, alpha=0.85, height=0.5)
        ax.text(r["low"], i + 0.38, f"{r['low']:,.0f}", ha="center", fontsize=7, color=GREY)
        ax.text(r["high"], i + 0.38, f"{r['high']:,.0f}", ha="center", fontsize=7, color=GREY)
    ax.axvline(v.price, color=RED, linestyle="--", linewidth=1.5)
    ax.annotate(
        f"Price {v.price:,.2f}",
        xy=(v.price, 1.0),
        xycoords=ax.get_xaxis_transform(),
        xytext=(0, 3),
        textcoords="offset points",
        color=RED,
        fontsize=8,
        ha="center",
        va="bottom",
    )
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("EUR per share", fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_title("Football field", loc="left", pad=18, fontsize=10, fontweight="bold", color=NAVY)


def _ai_section(fig, v):
    ex = v.extraction
    fig.text(
        0.05,
        0.37,
        "Top risks (AI extraction, by severity)",
        fontsize=10,
        fontweight="bold",
        color=NAVY,
    )
    if ex is None:
        fig.text(
            0.05,
            0.345,
            "No AI extraction available — run with --refresh",
            fontsize=9,
            color=GREY,
            style="italic",
        )
        return
    risks = sorted(ex.risks, key=lambda r: -r.severity)[:3]
    y = 0.345
    for r in risks:
        fig.text(
            0.05,
            y,
            _wrap(f"[{r.severity}/5] {r.category}: {r.description} (p.{r.page})", 105),
            fontsize=8.5,
            va="top",
        )
        y -= 0.045
    if not risks:
        fig.text(0.05, y, "No risks extracted.", fontsize=9, color=GREY)
    tone = ex.management_tone
    tone_txt = (
        f"Management tone: {tone.label}. {tone.rationale}"
        if tone is not None
        else "Management tone: not available"
    )
    fig.text(0.05, 0.19, _wrap(tone_txt, 105), fontsize=8.5, va="top", color=GREY)


def write_onepager(v, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(8.27, 11.69))
    _header(fig, v)
    _metrics(fig, v)
    _football(fig, v)
    _ai_section(fig, v)
    verd = verdict(v.scenarios["base"], v.price)
    fig.text(0.05, 0.12, "Verdict", fontsize=10, fontweight="bold", color=NAVY)
    fig.text(0.05, 0.085, verd, fontsize=20, fontweight="bold", color=VERDICT_COLOR[verd])
    fig.text(
        0.05,
        0.05,
        "Base DCF value vs price: >+10% undervalued, <-10% overvalued.",
        fontsize=8,
        color=GREY,
    )
    fig.text(0.5, 0.02, DISCLAIMER, fontsize=8, ha="center", color=GREY, style="italic")
    fig.savefig(path, format="pdf")
    plt.close(fig)
    return path
