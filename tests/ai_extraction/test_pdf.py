from pathlib import Path

import pymupdf
import pytest

from cac40val.ai_extraction.pdf import DEFAULT_KEYWORDS, locate_sections, read_pages


@pytest.fixture
def mini_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open()
    for text in ["Cover page", "Outlook for the year", "Table of numbers"]:
        doc.new_page().insert_text((72, 72), text)
    path = tmp_path / "mini_deu.pdf"
    doc.save(path)
    doc.close()
    return path


def test_read_pages_one_based(mini_pdf):
    pages = read_pages(mini_pdf)
    assert [n for n, _ in pages] == [1, 2, 3]
    assert "Outlook" in pages[1][1]


def test_locate_sections_finds_keyword_and_window(mini_pdf):
    found = locate_sections(read_pages(mini_pdf), DEFAULT_KEYWORDS)
    assert [n for n, _ in found] == [2, 3]


def test_locate_sections_no_match(mini_pdf):
    assert locate_sections(read_pages(mini_pdf), ["zzz"]) == []
