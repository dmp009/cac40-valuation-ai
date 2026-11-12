"""Download of the latest DEU (Document d'enregistrement universel) PDFs."""

from pathlib import Path

from cac40val.config import Company
from cac40val.ingest import save_raw


def download_deu(company: Company, dest: Path = Path("data/raw/deu")) -> Path | None:
    """Download the DEU PDF to dest/<ticker>.pdf. None if no URL; skips if already present."""
    if not company.deu_url:
        return None
    target = dest / f"{company.ticker}.pdf"
    if target.exists():
        return target
    import requests

    resp = requests.get(company.deu_url, timeout=120)
    resp.raise_for_status()
    # Lineage: timestamped raw copy next to the stable-named file.
    save_raw("deu", resp.content, "pdf", root=dest.parent)
    dest.mkdir(parents=True, exist_ok=True)
    target.write_bytes(resp.content)
    return target
