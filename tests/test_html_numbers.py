"""Numbers in the HTML report follow the rules of the language.

The report used to show a decimal point while the sentences used a comma (CHANGELOG 2.0.0).
Score, worst finding, points, duration, speed and shares go through the language formatter. The
technical sentence and the evidence JSON stay in machine notation, like the CSV (ADR-009), so
the test does not look at them.
"""

from __future__ import annotations

import html
import re

import pytest

from sitetriage.config import load_config
from sitetriage.models import DomainReport, Finding, Reason, Unknown
from sitetriage.report import html_out

# A decimal number, not a version ("2.0.0") or an IP address: no point or digit on either side.
DECIMAL = re.compile(r"(?<![\d.])\d+\.\d+(?![\d.])")
NOT_TEXT = re.compile(r'<(style|script|pre)\b.*?</\1>|<p class="tech">.*?</p>', re.DOTALL)


def text(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", NOT_TEXT.sub(" ", page)))


def page(lang: str) -> str:
    finding = Finding(
        domain="d.rs",
        check_id="seo.title.missing",
        level=1,
        category="seo",
        severity="medium",
        evidence={"page": "https://d.rs/", "title_length": 0},
        weight=10.4,
    )
    reports = [
        DomainReport(domain="d.rs", findings=[finding], total_score=99.4, max_finding_weight=10.4, rank=1),
        DomainReport(
            domain="e.rs",
            status="partial",
            partial_causes=["budget"],
            unknowns=[Unknown(check_id="infra.robots.missing", reason=Reason("requires.robots"))],
            rank=2,
        ),
        DomainReport(domain="f.rs", rank=3),
    ]
    return html_out.render(reports, load_config(), duration_s=3.44, lang=lang)


@pytest.mark.parametrize("number", ["99,4", "10,4", "3,4 s", "4,8 Mb/s", "0,6 MB/s", "33,3 %"])
def test_serbian_html_has_no_decimal_point_in_the_text(number):
    content = text(page("sr"))
    assert not DECIMAL.findall(content)
    assert number in content


@pytest.mark.parametrize("number", ["99.4", "10.4", "3.4 s", "4.8 Mb/s", "0.6 MB/s", "33.3 %"])
def test_english_html_has_a_decimal_point(number):
    assert number in text(page("en"))
