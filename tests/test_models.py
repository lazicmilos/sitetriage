import json

import pytest

from skener.models import (
    CheckResult,
    Entry,
    Finding,
    OpenGraph,
    PageSnapshot,
    SiteSnapshot,
    from_dict,
    to_jsonable,
)


def _snapshot() -> SiteSnapshot:
    return SiteSnapshot(
        domain="d.rs",
        industry="hotel",
        fetched_at="2026-09-22T09:14:03Z",
        entry=Entry(requested_url="https://d.rs/", final_url="https://d.rs/", status=200),
        pages=[
            PageSnapshot(
                url="https://d.rs/",
                status=200,
                og=OpenGraph(title="Naslov"),
                headers={"content-encoding": "gzip"},
                hreflang=["sr", "en"],
            )
        ],
    )


def test_serijalizacija_bez_gubitka():
    original = _snapshot()
    payload = json.loads(json.dumps(to_jsonable(original)))
    restored = from_dict(SiteSnapshot, payload)
    assert to_jsonable(restored) == to_jsonable(original)
    assert restored.pages[0].og.title == "Naslov"
    assert restored.home is restored.pages[0]


def test_nepoznata_polja_se_ignorisu():
    """Stariji snapshot sa disk-a ne sme da obori noviji kod."""
    payload = to_jsonable(_snapshot())
    payload["polje_iz_buducnosti"] = 1
    assert from_dict(SiteSnapshot, payload).domain == "d.rs"


def test_unknown_bez_razloga_je_bug():
    with pytest.raises(ValueError, match="unknown"):
        CheckResult(check_id="seo.title.missing", status="unknown")


def test_finding_bez_nalaza_je_bug():
    with pytest.raises(ValueError, match="bez ijednog nalaza"):
        CheckResult(check_id="seo.title.missing", status="finding")


def test_ok_sa_nalazom_je_bug():
    finding = Finding(
        domain="d.rs",
        check_id="seo.title.missing",
        level=1,
        category="seo",
        severity="high",
    )
    with pytest.raises(ValueError, match="status nije"):
        CheckResult(check_id="seo.title.missing", status="ok", findings=[finding])
