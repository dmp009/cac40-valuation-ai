"""Typed loaders for the YAML configuration files."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Company:
    ticker: str
    name: str
    currency: str
    is_target: bool
    deu_url: str | None = None
    section_hints: list[str] = field(default_factory=list)


@dataclass
class Settings:
    llm_model: str
    tax_rate: float
    terminal_growth: float
    rf_override: float | None
    erp_override: float | None
    benchmark_ticker: str


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_companies(path: Path = Path("config/sources.yaml")) -> list[Company]:
    data = _read_yaml(path)
    return [
        Company(
            ticker=c["ticker"],
            name=c["name"],
            currency=c["currency"],
            is_target=bool(c["is_target"]),
            deu_url=c.get("deu_url"),
            section_hints=list(c.get("section_hints") or []),
        )
        for c in data["companies"]
    ]


def load_settings(path: Path = Path("config/settings.yaml")) -> Settings:
    data = _read_yaml(path)
    return Settings(
        llm_model=data["llm_model"],
        tax_rate=float(data["tax_rate"]),
        terminal_growth=float(data["terminal_growth"]),
        rf_override=data.get("rf_override"),
        erp_override=data.get("erp_override"),
        benchmark_ticker=data["benchmark_ticker"],
    )


def load_overrides(ticker: str, root: Path = Path("config/assumptions")) -> dict:
    path = root / f"{ticker}.yaml"
    if not path.exists():
        return {}
    return _read_yaml(path)
