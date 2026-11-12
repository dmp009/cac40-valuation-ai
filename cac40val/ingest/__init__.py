"""Ingestion of market data, rates and filings, with raw-response lineage."""

from datetime import UTC, datetime
from pathlib import Path

RAW_ROOT = Path("data/raw")


def save_raw(source: str, content: str | bytes, ext: str, root: Path = RAW_ROOT) -> Path:
    """Save a raw response under <root>/<source>/<UTC timestamp>.<ext>."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / source / f"{stamp}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path
