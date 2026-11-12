"""End-to-end orchestration: ingest -> warehouse -> AI extraction -> valuation -> outputs."""

import argparse
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from cac40val.ai_extraction.extract import get_extraction, to_rows
from cac40val.ai_extraction.models import Extraction
from cac40val.config import (
    Company,
    Settings,
    load_companies,
    load_overrides,
    load_settings,
)
from cac40val.valuation import comps, dcf, wacc
from cac40val.valuation.forecast import Drivers, build_scenarios, historical_drivers, project
from cac40val.warehouse.db import connect, read_financials, read_prices, upsert
from cac40val.warehouse.quality import run_quality_checks, write_quality_report

logger = logging.getLogger(__name__)

DB_PATH = Path("data/warehouse.duckdb")
SNAPSHOT_DIR = Path("data/snapshot")
TABLES = [
    "dim_company",
    "dim_date",
    "fact_financials",
    "fact_prices",
    "fact_market_params",
    "fact_fx",
    "fact_ai_extraction",
]
BETA_MONTHS = 60
TRADING_DAYS_52W = 252
_GROWTH_METRICS = {"revenue_growth", "organic_growth"}
_MARGIN_METRICS = {"operating_margin", "ebit_margin"}
_PCT = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*(?:(?:-|–|to|à)\s*(-?\d+(?:[.,]\d+)?))?\s*%")


@dataclass
class CompanyValuation:
    ticker: str
    price: float
    scenarios: dict[str, float]
    wacc: float
    g: float
    ev_base: float
    sensitivity: pd.DataFrame
    projections: dict[str, pd.DataFrame]
    drivers: dict[str, Drivers]
    comps_implied: pd.DataFrame
    football: pd.DataFrame
    extraction: Extraction | None
    tv_gordon_vs_exit_gap: float
    # Inputs needed to rebuild the model in Excel with live formulas.
    last_revenue: float
    last_nwc: float  # memo only (latest actual operating NWC); not used in the projection
    net_debt: float
    minorities: float
    associates: float
    shares: float
    rf: float
    erp: float
    beta: float
    kd: float
    tax: float
    market_cap: float
    gross_debt: float
    historicals: pd.DataFrame
    peers: pd.DataFrame


# ---------------------------------------------------------------- guidance


def _parse_pct(statement: str) -> float | None:
    m = _PCT.search(statement)
    if not m:
        return None
    lo = float(m.group(1).replace(",", "."))
    hi = float(m.group(2).replace(",", ".")) if m.group(2) else lo
    return (lo + hi) / 2 / 100


def guidance_from_extraction(ex: Extraction | None) -> tuple[float | None, float | None]:
    """(growth, margin) guidance parsed from percentages in guidance statements."""
    if ex is None:
        return None, None
    growth = margin = None
    for item in ex.guidance:
        value = _parse_pct(item.statement)
        if value is None:
            continue
        if item.metric in _GROWTH_METRICS and growth is None:
            growth = -abs(value) if item.direction == "down" else value
        elif item.metric in _MARGIN_METRICS and margin is None:
            margin = value
    return growth, margin


# ---------------------------------------------------------------- data access


def valuation_date(con: duckdb.DuckDBPyConnection, settings: Settings) -> pd.Timestamp:
    row = con.execute(
        "SELECT max(date) FROM fact_prices WHERE ticker = ?", [settings.benchmark_ticker]
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"No benchmark prices for {settings.benchmark_ticker}")
    return pd.Timestamp(row[0])


def _fx(con: duckdb.DuckDBPyConnection, currency: str, date: pd.Timestamp) -> float:
    if currency == "EUR":
        return 1.0
    row = con.execute(
        "SELECT eur_per_unit FROM fact_fx WHERE currency = ? AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        [currency, date.date()],
    ).fetchone()
    if row is None:
        raise ValueError(f"No FX rate for {currency} on or before {date.date()}")
    return float(row[0])


def _latest(wide: pd.DataFrame, item: str) -> float:
    if item not in wide:
        return math.nan
    s = wide[item].dropna()
    return float(s.iloc[-1]) if len(s) else math.nan


def _fin_currency(con: duckdb.DuckDBPyConnection, ticker: str, default: str) -> str:
    row = con.execute(
        "SELECT currency FROM fact_financials WHERE ticker = ? AND currency IS NOT NULL LIMIT 1",
        [ticker],
    ).fetchone()
    return row[0] if row else default


def _company_row(con: duckdb.DuckDBPyConnection, company: Company, date: pd.Timestamp) -> dict:
    """EUR-converted snapshot of a company at the valuation date (NaN where missing)."""
    fin = read_financials(con, company.ticker)
    wide = fin.pivot_table(index="fiscal_year", columns="line_item", values="value").sort_index()
    fin_ccy = _fin_currency(con, company.ticker, company.reporting_currency or company.currency)
    fx_fin = _fx(con, fin_ccy, date)
    fx_px = _fx(con, company.currency, date)
    closes = con.execute(
        "SELECT close FROM fact_prices WHERE ticker = ? AND date <= ? ORDER BY date",
        [company.ticker, date.date()],
    ).df()["close"]
    price = float(closes.iloc[-1]) * fx_px if len(closes) else math.nan
    shares = _latest(wide, "shares_outstanding")

    def eur(item: str) -> float:
        return _latest(wide, item) * fx_fin

    def eur_default0(item: str) -> float:
        v = eur(item)
        if math.isnan(v):
            logger.info("%s: %s missing, defaulting to 0", company.ticker, item)
            return 0.0
        return v

    pretax, tax = eur("pretax_income"), eur("tax_expense")
    return {
        "ticker": company.ticker,
        "price_eur": price,
        "shares": shares,
        "market_cap_eur": price * shares,
        "gross_debt_eur": eur("gross_debt"),
        "net_debt_eur": eur("gross_debt") - eur("cash"),
        "minorities_eur": eur_default0("minorities"),
        "associates_eur": eur_default0("associates"),
        "revenue_eur": eur("revenue"),
        "ebitda_eur": eur("ebitda"),
        "net_income_eur": pretax - tax,
        "nwc_eur": eur("nwc"),
        "fx_fin": fx_fin,
    }


def build_multiples(
    con: duckdb.DuckDBPyConnection, companies: list[Company], date: pd.Timestamp
) -> pd.DataFrame:
    rows = []
    for c in companies:
        try:
            rows.append(_company_row(con, c, date))
        except ValueError as exc:
            logger.warning("Skipping %s in comps: %s", c.ticker, exc)
    return comps.compute_multiples(pd.DataFrame(rows))


# ---------------------------------------------------------------- WACC inputs


def resolve_market_params(
    con: duckdb.DuckDBPyConnection, settings: Settings, date: pd.Timestamp
) -> tuple[float, float]:
    """Resolve rf/erp (overrides first), store them at the valuation date, return them."""
    from cac40val.ingest.rates import load_erp

    if settings.rf_override is not None:
        rf = float(settings.rf_override)
    else:
        row = con.execute(
            "SELECT rf_oat10y FROM fact_market_params WHERE rf_oat10y IS NOT NULL "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No risk-free rate available (ingest OAT yields or set rf_override)")
        rf = float(row[0])
    erp = float(settings.erp_override) if settings.erp_override is not None else load_erp()
    upsert(
        con,
        "fact_market_params",
        pd.DataFrame({"date": [date.date()], "rf_oat10y": [rf], "erp_france": [erp]}),
    )
    return rf, erp


def _beta(con: duckdb.DuckDBPyConnection, ticker: str, benchmark: str) -> float:
    stock = read_prices(con, ticker).resample("ME").last().pct_change()
    bench = read_prices(con, benchmark).resample("ME").last().pct_change()
    pairs = pd.concat([stock, bench], axis=1, join="inner").dropna().tail(BETA_MONTHS)
    if len(pairs) < wacc.MIN_BETA_OBSERVATIONS:
        logger.warning("%s: only %d monthly returns, falling back to beta 1.0", ticker, len(pairs))
        return 1.0
    raw = wacc.regress_beta(pairs.iloc[:, 0], pairs.iloc[:, 1])
    return wacc.blume_adjust(raw)


# ---------------------------------------------------------------- valuation


def value_company(
    con: duckdb.DuckDBPyConnection,
    company: Company,
    settings: Settings,
    peers_multiples: pd.DataFrame,
    extraction: Extraction | None,
) -> CompanyValuation:
    ticker = company.ticker
    date = valuation_date(con, settings)
    rows = peers_multiples[peers_multiples["ticker"] == ticker]
    if rows.empty:
        raise ValueError(f"{ticker} missing from peers_multiples")
    row = rows.iloc[0]
    for key in ("price_eur", "shares", "market_cap_eur", "net_debt_eur", "revenue_eur"):
        if not math.isfinite(row[key]):
            raise ValueError(f"{ticker}: required input '{key}' is missing")
    price, shares = float(row["price_eur"]), float(row["shares"])

    # --- WACC
    mp = con.execute(
        "SELECT rf_oat10y, erp_france FROM fact_market_params WHERE rf_oat10y IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if mp is None:
        raise ValueError("fact_market_params is empty")
    rf, erp = float(mp[0]), float(mp[1])
    beta = _beta(con, ticker, settings.benchmark_ticker)
    ke = wacc.cost_of_equity(rf, beta, erp)
    fin = read_financials(con, ticker)
    wide = fin.pivot_table(index="fiscal_year", columns="line_item", values="value").sort_index()
    interest = _latest(wide, "interest_expense")
    avg_debt = float(wide["gross_debt"].dropna().tail(2).mean()) if "gross_debt" in wide else 0.0
    kd = wacc.cost_of_debt(
        0.0 if math.isnan(interest) else interest, 0.0 if math.isnan(avg_debt) else avg_debt, rf
    )
    debt = row["gross_debt_eur"]
    debt = 0.0 if not math.isfinite(debt) else float(debt)
    rate = wacc.wacc(float(row["market_cap_eur"]), debt, ke, kd, settings.tax_rate)
    g = settings.terminal_growth

    # --- projections
    g_guid, m_guid = guidance_from_extraction(extraction)
    hist = historical_drivers(fin)
    drivers = build_scenarios(hist, g_guid, m_guid, load_overrides(ticker), settings.tax_rate)
    last_rev = float(row["revenue_eur"])
    last_nwc = float(row["nwc_eur"]) if math.isfinite(row["nwc_eur"]) else 0.0
    projections = {n: project(last_rev, d) for n, d in drivers.items()}

    minorities = float(row["minorities_eur"])
    associates = float(row["associates_eur"])
    net_debt = float(row["net_debt_eur"])
    evs, scenarios = {}, {}
    for name, proj in projections.items():
        evs[name] = dcf.enterprise_value(list(proj["fcff"]), rate, g)
        scenarios[name] = dcf.equity_bridge(evs[name], net_debt, minorities, associates) / shares
    base = projections["base"]
    sens = dcf.sensitivity_grid(
        list(base["fcff"]), rate, g, net_debt, shares, minorities, associates
    )

    # --- comps (peer set = everyone but the target)
    stats = comps.peer_stats(peers_multiples, exclude=[ticker])
    implied = comps.implied_values(row, stats, shares)
    median_mult = stats.loc["ev_ebitda", "median"]
    tv_gordon = dcf.gordon_terminal_value(float(base["fcff"].iloc[-1]), rate, g)
    if pd.notna(median_mult):
        tv_exit = dcf.exit_multiple_terminal_value(float(base["ebitda"].iloc[-1]), median_mult)
        gap = (tv_gordon - tv_exit) / tv_exit if tv_exit else math.nan
    else:
        gap = math.nan

    closes = (
        con.execute(
            "SELECT close FROM fact_prices WHERE ticker = ? AND date <= ? ORDER BY date",
            [ticker, date.date()],
        )
        .df()["close"]
        .tail(TRADING_DAYS_52W)
    )
    fx_px = _fx(con, company.currency, date)
    week52 = (float(closes.min()) * fx_px, float(closes.max()) * fx_px)
    football = comps.football_field(
        (scenarios["bear"], scenarios["bull"]),
        (float(implied.loc["ev_ebitda", "low"]), float(implied.loc["ev_ebitda", "high"])),
        week52,
        price,
    )
    return CompanyValuation(
        ticker=ticker,
        price=price,
        scenarios=scenarios,
        wacc=rate,
        g=g,
        ev_base=float(evs["base"]),
        sensitivity=sens,
        projections=projections,
        drivers=drivers,
        comps_implied=implied,
        football=football,
        extraction=extraction,
        tv_gordon_vs_exit_gap=float(gap),
        last_revenue=last_rev,
        last_nwc=last_nwc,
        net_debt=net_debt,
        minorities=minorities,
        associates=associates,
        shares=shares,
        rf=rf,
        erp=erp,
        beta=beta,
        kd=float(kd),
        tax=settings.tax_rate,
        market_cap=float(row["market_cap_eur"]),
        gross_debt=debt,
        historicals=wide,
        peers=peers_multiples,
    )


# ---------------------------------------------------------------- outputs


def _clean(x):
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def write_outputs(valuations: list[CompanyValuation], out_dir: Path = Path("outputs")) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        {
            "ticker": v.ticker,
            "price": _clean(v.price),
            "scenarios": {k: _clean(float(x)) for k, x in v.scenarios.items()},
            "wacc": _clean(v.wacc),
            "g": _clean(v.g),
            "ev_base": _clean(v.ev_base),
            "upside_base": _clean(v.scenarios["base"] / v.price - 1),
            "tv_gordon_vs_exit_gap": _clean(v.tv_gordon_vs_exit_gap),
            "driver_sources": v.drivers["base"].sources,
        }
        for v in valuations
    ]
    (out_dir / "valuations.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    from cac40val.outputs.excel import write_excel
    from cac40val.outputs.onepager import write_onepager

    for v in valuations:
        target = out_dir / v.ticker
        target.mkdir(parents=True, exist_ok=True)
        write_excel(v, target / f"{v.ticker}_model.xlsx")
        write_onepager(v, target / f"{v.ticker}_onepager.pdf")


def export_snapshot(con: duckdb.DuckDBPyConnection, out_dir: Path = SNAPSHOT_DIR) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        target = (out_dir / f"{table}.parquet").as_posix().replace("'", "''")
        con.execute(f"COPY (SELECT * FROM {table}) TO '{target}' (FORMAT PARQUET)")


def load_snapshot(dir: Path = SNAPSHOT_DIR) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with every warehouse table loaded from the parquet snapshot."""
    con = connect(":memory:")
    for table in TABLES:
        path = (Path(dir) / f"{table}.parquet").as_posix().replace("'", "''")
        con.execute(f"INSERT INTO {table} SELECT * FROM read_parquet('{path}')")
    return con


# ---------------------------------------------------------------- ingest


def _ingest(con: duckdb.DuckDBPyConnection, companies: list[Company], settings: Settings) -> None:
    from cac40val.ingest.market import fetch_company, fetch_fx, fetch_prices
    from cac40val.ingest.rates import fetch_oat10y, load_erp

    upsert(
        con,
        "dim_company",
        pd.DataFrame(
            {
                "ticker": [c.ticker for c in companies],
                "name": [c.name for c in companies],
                "country": None,
                "currency": [c.currency for c in companies],
                "sector": "Luxury & Consumer",
                "is_target": [c.is_target for c in companies],
            }
        ),
    )
    for c in companies:
        try:
            fin, prices = fetch_company(c)
        except Exception:
            logger.exception("Ingest failed for %s", c.ticker)
            continue
        upsert(con, "fact_financials", fin)
        upsert(con, "fact_prices", prices)
    try:
        upsert(con, "fact_prices", fetch_prices(settings.benchmark_ticker))
    except Exception:
        logger.exception("Benchmark ingest failed")
    try:
        oat = fetch_oat10y()
        oat["erp_france"] = float(settings.erp_override) if settings.erp_override else load_erp()
        upsert(con, "fact_market_params", oat)
    except Exception:
        logger.exception("OAT ingest failed")

    date = valuation_date(con, settings)
    currencies = {c.currency for c in companies}
    currencies |= {
        r[0]
        for r in con.execute("SELECT DISTINCT currency FROM fact_financials").fetchall()
        if r[0]
    }
    fx_rows = []
    for cur in sorted(currencies - {"EUR"}):
        try:
            fx_rows.append(
                {
                    "date": date.date(),
                    "currency": cur,
                    "eur_per_unit": fetch_fx(cur, str(date.date())),
                }
            )
        except Exception:
            logger.exception("FX ingest failed for %s", cur)
    upsert(con, "fact_fx", pd.DataFrame(fx_rows, columns=["date", "currency", "eur_per_unit"]))
    dates = con.execute("SELECT DISTINCT date FROM fact_prices").df()["date"]
    ts = pd.to_datetime(dates)
    upsert(
        con,
        "dim_date",
        pd.DataFrame(
            {"date": dates, "year": ts.dt.year, "month": ts.dt.month, "quarter": ts.dt.quarter}
        ),
    )


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(prog="cac40val.pipeline")
    p.add_argument("--refresh", action="store_true", help="re-run AI extraction via the API")
    p.add_argument("--offline", action="store_true", help="skip network ingest")
    p.add_argument("--only-ai", action="store_true", help="only run AI extraction")
    p.add_argument("--tickers", nargs="+", help="restrict valuation targets")
    args = p.parse_args(argv)

    companies = load_companies()
    settings = load_settings()
    con = connect(DB_PATH)
    if not args.offline and not args.only_ai:
        _ingest(con, companies, settings)

    write_quality_report(run_quality_checks(con))

    client = None
    if args.refresh and os.environ.get("ANTHROPIC_API_KEY"):
        from cac40val.ai_extraction.llm import AnthropicClient

        client = AnthropicClient(settings)
    targets = [
        c for c in companies if c.is_target and (not args.tickers or c.ticker in args.tickers)
    ]
    extractions: dict[str, Extraction | None] = {}
    for c in targets:
        row = con.execute(
            "SELECT max(fiscal_year) FROM fact_financials WHERE ticker = ?", [c.ticker]
        ).fetchone()
        if row is None or row[0] is None:
            extractions[c.ticker] = None
            continue
        ex = get_extraction(c, int(row[0]), refresh=args.refresh, client=client)
        if ex is not None:
            upsert(con, "fact_ai_extraction", to_rows(ex))
        extractions[c.ticker] = ex
    if args.only_ai:
        return 0

    date = valuation_date(con, settings)
    resolve_market_params(con, settings, date)
    multiples = build_multiples(con, companies, date)
    valuations = []
    for c in targets:
        try:
            v = value_company(con, c, settings, multiples, extractions.get(c.ticker))
        except Exception:
            logger.exception("Valuation failed for %s", c.ticker)
            continue
        logger.info(
            "%s price %.2f bear/base/bull %.2f/%.2f/%.2f WACC %.2f%%",
            c.ticker,
            v.price,
            v.scenarios["bear"],
            v.scenarios["base"],
            v.scenarios["bull"],
            v.wacc * 100,
        )
        valuations.append(v)
    write_outputs(valuations)
    export_snapshot(con)
    return 0 if len(valuations) == len(targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
