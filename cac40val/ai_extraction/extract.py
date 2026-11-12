"""Orchestration: locate sections, call the LLM, validate item by item, cache."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from cac40val.ai_extraction.llm import PROMPT_PATH, LLMClient
from cac40val.ai_extraction.models import (
    Extraction,
    ExtractionPayload,
    GuidanceItem,
    ManagementTone,
    RiskItem,
    SegmentItem,
)
from cac40val.ai_extraction.pdf import DEFAULT_KEYWORDS, locate_sections, read_pages
from cac40val.config import Company
from cac40val.ingest.deu import download_deu

logger = logging.getLogger(__name__)

MAX_CHARS = 150_000
DEFAULT_MODEL = "unknown"


def _validate_items(raw_items, model_cls) -> tuple[list, int]:
    kept, rejected = [], 0
    if not isinstance(raw_items, list):
        return kept, 1 if raw_items else 0
    for item in raw_items:
        try:
            kept.append(model_cls.model_validate(item))
        except ValidationError:
            rejected += 1
    return kept, rejected


def parse_extraction(raw: dict, ticker: str, fiscal_year: int, model: str) -> Extraction:
    """Validate item by item; invalid items (incl. missing page) are dropped and counted."""
    guidance, r1 = _validate_items(raw.get("guidance"), GuidanceItem)
    risks, r2 = _validate_items(raw.get("risks"), RiskItem)
    segments, r3 = _validate_items(raw.get("segments"), SegmentItem)
    rejected = r1 + r2 + r3
    try:
        tone = ManagementTone.model_validate(raw.get("management_tone"))
    except ValidationError:
        tone = ManagementTone(label="neutral", rationale="Tone not extracted (invalid output)")
        rejected += 1
    return Extraction(
        ticker=ticker,
        fiscal_year=fiscal_year,
        model=model,
        extracted_at=datetime.now(UTC).replace(tzinfo=None),
        guidance=guidance,
        risks=risks,
        segments=segments,
        management_tone=tone,
        rejected_count=rejected,
    )


def segment_check(ex: Extraction, total_revenue_eur_m: float, tol: float = 0.02) -> bool:
    """True if the segment revenues sum to the reported total within tolerance."""
    total = sum(s.revenue_eur_m for s in ex.segments)
    return abs(total - total_revenue_eur_m) <= tol * total_revenue_eur_m


def _build_prompt(pages: list[tuple[int, str]]) -> str:
    parts = [PROMPT_PATH.read_text(encoding="utf-8")]
    used = 0
    for n, text in pages:
        if used + len(text) > MAX_CHARS:
            logger.warning("Located text exceeds %d chars; truncating from page %d", MAX_CHARS, n)
            break
        parts.append(f"[page {n}]\n{text}")
        used += len(text)
    return "\n\n".join(parts)


def _no_cache(ticker: str) -> None:
    logger.info("No AI cache for %s; run with --refresh and ANTHROPIC_API_KEY to extract", ticker)


def get_extraction(
    company: Company,
    fiscal_year: int,
    *,
    refresh: bool,
    client: LLMClient | None,
    cache_dir: Path = Path("data/ai_cache"),
    model: str | None = None,
) -> Extraction | None:
    cache_file = cache_dir / f"{company.ticker}_{fiscal_year}.json"
    if cache_file.exists():
        return Extraction.model_validate_json(cache_file.read_text(encoding="utf-8"))
    if not refresh or client is None:
        _no_cache(company.ticker)
        return None
    pdf_path = download_deu(company)
    if pdf_path is None:
        _no_cache(company.ticker)
        return None
    keywords = [*DEFAULT_KEYWORDS, *company.section_hints]
    pages = locate_sections(read_pages(pdf_path), keywords)
    raw = client.extract(_build_prompt(pages), ExtractionPayload)
    ex = parse_extraction(
        raw, company.ticker, fiscal_year, model or getattr(client, "_model", DEFAULT_MODEL)
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(ex.model_dump_json(indent=2), encoding="utf-8")
    return ex


def to_rows(ex: Extraction) -> pd.DataFrame:
    """Complete row set for fact_ai_extraction (upsert replaces by ticker/fiscal_year)."""
    base = {
        "ticker": ex.ticker,
        "fiscal_year": ex.fiscal_year,
        "model": ex.model,
        "extracted_at": ex.extracted_at,
    }
    rows = []
    for g in ex.guidance:
        rows.append(
            {
                **base,
                "field": "guidance",
                "value": g.model_dump_json(),
                "value_num": None,
                "page": g.page,
            }
        )
    for r in ex.risks:
        rows.append(
            {
                **base,
                "field": "risk",
                "value": r.model_dump_json(),
                "value_num": None,
                "page": r.page,
            }
        )
    for s in ex.segments:
        rows.append(
            {
                **base,
                "field": "segment",
                "value": s.model_dump_json(),
                "value_num": s.revenue_eur_m,
                "page": s.page,
            }
        )
    rows.append(
        {
            **base,
            "field": "tone",
            "value": ex.management_tone.model_dump_json(),
            "value_num": None,
            "page": None,
        }
    )
    df = pd.DataFrame(rows)
    df["page"] = df["page"].astype("Int64")
    df["value_num"] = df["value_num"].astype("float64")
    return df
