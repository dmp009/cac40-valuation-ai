"""Verdict thresholds shared by the Excel model and the PDF one-pager."""

UNDERVALUED_ABOVE = 1.10
OVERVALUED_BELOW = 0.90


def verdict(base: float, price: float) -> str:
    if base > price * UNDERVALUED_ABOVE:
        return "Undervalued"
    if base < price * OVERVALUED_BELOW:
        return "Overvalued"
    return "Fairly valued"
