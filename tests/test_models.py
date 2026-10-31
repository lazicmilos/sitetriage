import json

import pytest

from sitetriage.models import (
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


@pytest.mark.parametrize(
    "old, new",
    [("restoran", "restaurant"), ("zdravstvo", "healthcare"), ("institucija", "institution"),
     ("ostalo", "other"), ("hotel", "hotel")],
)
def test_pre_3_0_snapshot_gets_the_english_industry(tmp_path, old, new):
    """Snapshot field names did not change in 3.0, only industry values (ADR-012). An old value
    would fall back to `other` multipliers without a word, so `recheck` maps it on read."""
    from sitetriage import store

    data = to_jsonable(_snapshot())
    data.update(industry=old, scanner_version="2.0.0")
    folder = tmp_path / "d.rs"
    folder.mkdir()
    (folder / store.SITE_NAME).write_text(json.dumps(data), encoding="utf-8")
    [(site, browser)] = list(store.read_all(tmp_path))
    assert site.industry == new and browser is None
