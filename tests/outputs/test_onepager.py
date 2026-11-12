import fitz
import pytest
from conftest import make_extraction, make_valuation

from cac40val.outputs.onepager import verdict, write_onepager


@pytest.mark.parametrize(
    "ex", [None, make_extraction(), make_extraction(tone=False)], ids=["none", "full", "no_tone"]
)
def test_onepager_is_single_page_pdf(tmp_path, ex):
    path = write_onepager(make_valuation(ex), tmp_path / "o.pdf")
    assert path.read_bytes().startswith(b"%PDF")
    doc = fitz.open(path)
    assert doc.page_count == 1
    text = doc[0].get_text()
    assert "Educational project, not investment advice" in text
    if ex is None:
        assert "No AI extraction available" in text
    else:
        assert "China slowdown" in text


def test_verdict_thresholds():
    assert verdict(115, 100) == "Undervalued"
    assert verdict(100, 100) == "Fairly valued"
    assert verdict(85, 100) == "Overvalued"
