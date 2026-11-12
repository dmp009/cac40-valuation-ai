import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymupdf

from cac40val.ai_extraction import extract as ex_mod
from cac40val.ai_extraction.extract import (
    get_extraction,
    parse_extraction,
    segment_check,
    to_rows,
)
from cac40val.ai_extraction.models import Extraction, ManagementTone
from cac40val.config import Company
from cac40val.warehouse.db import connect, upsert

FIXTURE = Path(__file__).parent.parent / "fixtures" / "llm_response.json"
CO = Company(ticker="MC.PA", name="LVMH", currency="EUR", is_target=True, deu_url="http://x")


def _raw():
    return json.loads(FIXTURE.read_text())


class FakeClient:
    def __init__(self, raw):
        self.raw = raw
        self.prompts = []

    def extract(self, prompt, schema):
        self.prompts.append(prompt)
        return self.raw


class BoomClient:
    def extract(self, prompt, schema):
        raise AssertionError("client must not be called")


def test_fact_without_page_is_rejected():
    raw = _raw()
    del raw["risks"][1]["page"]
    ex = parse_extraction(raw, "MC.PA", 2025, "m")
    assert len(ex.risks) == 1
    assert ex.rejected_count == 1


def test_malformed_item_rejected_others_kept():
    raw = _raw()
    raw["risks"][0]["severity"] = 9
    ex = parse_extraction(raw, "MC.PA", 2025, "m")
    assert len(ex.risks) == 1 and len(ex.guidance) == 1
    assert ex.rejected_count == 1


def test_bad_tone_falls_back_to_neutral_and_counts():
    raw = _raw()
    raw["management_tone"] = {"label": "euphoric", "rationale": "x"}
    ex = parse_extraction(raw, "MC.PA", 2025, "m")
    assert ex.management_tone.label == "neutral"
    assert ex.rejected_count == 1


def test_segment_check_tolerance():
    ex = parse_extraction(_raw(), "MC.PA", 2025, "m")  # segments sum 99
    assert segment_check(ex, 100.0) is True
    assert segment_check(ex, 110.0) is False


def test_cache_hit_does_not_call_client(tmp_path):
    ex = parse_extraction(_raw(), "MC.PA", 2025, "m")
    (tmp_path / "MC.PA_2025.json").write_text(ex.model_dump_json(indent=2))
    got = get_extraction(CO, 2025, refresh=True, client=BoomClient(), cache_dir=tmp_path)
    assert got == ex


def test_cache_hit_without_refresh(tmp_path):
    ex = parse_extraction(_raw(), "MC.PA", 2025, "m")
    (tmp_path / "MC.PA_2025.json").write_text(ex.model_dump_json(indent=2))
    assert get_extraction(CO, 2025, refresh=False, client=None, cache_dir=tmp_path) == ex


def test_no_cache_no_refresh_returns_none_with_message(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        got = get_extraction(CO, 2025, refresh=False, client=BoomClient(), cache_dir=tmp_path)
    assert got is None
    assert (
        "No AI cache for MC.PA; run with --refresh and ANTHROPIC_API_KEY to extract" in caplog.text
    )


def test_refresh_without_client_returns_none(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        assert get_extraction(CO, 2025, refresh=True, client=None, cache_dir=tmp_path) is None
    assert "No AI cache for MC.PA" in caplog.text


def test_refresh_with_fake_client_writes_cache(tmp_path, monkeypatch):
    pdf = tmp_path / "MC.PA.pdf"
    doc = pymupdf.open()
    for t in ["Cover", "Outlook 2026", "Segments"]:
        doc.new_page().insert_text((72, 72), t)
    doc.save(pdf)
    monkeypatch.setattr(ex_mod, "download_deu", lambda company: pdf)
    client = FakeClient(_raw())
    cache = tmp_path / "cache"
    got = get_extraction(CO, 2025, refresh=True, client=client, cache_dir=cache)
    assert got is not None and len(got.risks) == 2
    assert "[page 2]" in client.prompts[0]
    f = cache / "MC.PA_2025.json"
    assert f.exists()
    assert Extraction.model_validate_json(f.read_text()) == got


def test_refresh_no_pdf_returns_none(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ex_mod, "download_deu", lambda company: None)
    with caplog.at_level(logging.INFO):
        got = get_extraction(CO, 2025, refresh=True, client=FakeClient(_raw()), cache_dir=tmp_path)
    assert got is None
    assert "No AI cache for MC.PA" in caplog.text


def test_to_rows_complete_and_upsertable():
    ex = parse_extraction(_raw(), "MC.PA", 2025, "m")
    ex = ex.model_copy(update={"extracted_at": datetime(2026, 1, 1)})
    df = to_rows(ex)
    assert sorted(df["field"].unique()) == ["guidance", "risk", "segment", "tone"]
    assert len(df) == 1 + 2 + 2 + 1
    tone = df[df["field"] == "tone"].iloc[0]
    assert pd.isna(tone["page"])
    seg = df[df["field"] == "segment"]
    assert sorted(seg["value_num"]) == [39.0, 60.0]
    assert json.loads(df[df["field"] == "risk"].iloc[0]["value"])["category"]
    con = connect(":memory:")
    assert upsert(con, "fact_ai_extraction", df) == 6


def test_tone_model():
    assert ManagementTone(label="positive", rationale="r").label == "positive"
