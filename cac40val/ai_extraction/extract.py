"""Orchestration: locate sections, call the LLM, validate item by item, cache."""

import logging
import re
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


def _validate_items(raw_items, model_cls, allowed_pages=None) -> tuple[list, int]:
    kept, rejected = [], 0
    if not isinstance(raw_items, list):
        return kept, 1 if raw_items else 0
    for item in raw_items:
        try:
            obj = model_cls.model_validate(item)
        except ValidationError:
            rejected += 1
            continue
        if allowed_pages is not None and obj.page not in allowed_pages:
            rejected += 1
            continue
        kept.append(obj)
    return kept, rejected


def parse_extraction(
    raw: dict,
    ticker: str,
    fiscal_year: int,
    model: str,
    allowed_pages: set[int] | None = None,
) -> Extraction:
    """Validate item by item; invalid items (incl. missing page) are dropped and counted."""
    guidance, r1 = _validate_items(raw.get("guidance"), GuidanceItem, allowed_pages)
    risks, r2 = _validate_items(raw.get("risks"), RiskItem, allowed_pages)
    segments, r3 = _validate_items(raw.get("segments"), SegmentItem, allowed_pages)
    rejected = r1 + r2 + r3
    try:
        tone = ManagementTone.model_validate(raw.get("management_tone"))
    except ValidationError:
        tone = None
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


_PAGE_TAG = re.compile(r"<(/?)(page)", flags=re.IGNORECASE)
_LEGACY_MARKER = re.compile(r"\[(page) ", flags=re.IGNORECASE)


def _escape_page_text(text: str) -> str:
    """Neutralise anything in untrusted page text that could open or close a page block."""
    text = _PAGE_TAG.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)
    return _LEGACY_MARKER.sub(lambda m: f"({m.group(1)} ", text)


def _build_prompt(pages: list[tuple[int, str]]) -> tuple[str, set[int]]:
    parts = [PROMPT_PATH.read_text(encoding="utf-8")]
    used = 0
    sent: set[int] = set()
    for n, text in pages:
        if used + len(text) > MAX_CHARS:
            logger.warning("Located text exceeds %d chars; truncating from page %d", MAX_CHARS, n)
            break
        parts.append(f'<page number="{n}">\n{_escape_page_text(text)}\n</page>')
        used += len(text)
        sent.add(n)
    return "\n\n".join(parts), sent


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
    if cache_file.exists() and not refresh:
        try:
            return Extraction.model_validate_json(cache_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:  # pydantic ValidationError is a ValueError
            logger.warning("Ignoring unreadable AI cache %s: %s", cache_file, exc)
    if not refresh or client is None:
        _no_cache(company.ticker)
        return None
    pdf_path = download_deu(company)
    if pdf_path is None:
        _no_cache(company.ticker)
        return None
    keywords = [*DEFAULT_KEYWORDS, *company.section_hints]
    pages = locate_sections(read_pages(pdf_path), keywords)
    prompt, sent_pages = _build_prompt(pages)
    raw = client.extract(prompt, ExtractionPayload)
    ex = parse_extraction(
        raw,
        company.ticker,
        fiscal_year,
        model or getattr(client, "_model", DEFAULT_MODEL),
        allowed_pages=sent_pages,
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
    if ex.management_tone is not None:
        rows.append(
            {
                **base,
                "field": "tone",
                "value": ex.management_tone.model_dump_json(),
                "value_num": None,
                "page": None,
            }
        )
    cols = [*base, "field", "value", "value_num", "page"]
    df = pd.DataFrame(rows, columns=cols)
    df["page"] = df["page"].astype("Int64")
    df["value_num"] = df["value_num"].astype("float64")
    return df
