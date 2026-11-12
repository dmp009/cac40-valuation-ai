"""PDF reading and keyword-based section location (keeps 1-based page numbers)."""

from collections.abc import Sequence
from pathlib import Path

DEFAULT_KEYWORDS: tuple[str, ...] = (
    "perspectives",
    "outlook",
    "facteurs de risque",
    "risk factors",
    "segment",
    "information sectorielle",
)


def read_pages(path: Path) -> list[tuple[int, str]]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [(i + 1, page.get_text()) for i, page in enumerate(doc)]


def locate_sections(
    pages: list[tuple[int, str]], keywords: Sequence[str], window: int = 2
) -> list[tuple[int, str]]:
    """Pages matching any keyword (case-insensitive) plus `window` following pages."""
    kws = [k.lower() for k in keywords if k]
    keep: set[int] = set()
    for idx, (_, text) in enumerate(pages):
        low = text.lower()
        if any(k in low for k in kws):
            keep.update(range(idx, min(idx + window + 1, len(pages))))
    return [pages[i] for i in sorted(keep)]
