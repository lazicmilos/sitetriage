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


def test_serialization_is_lossless():
    original = _snapshot()
    payload = json.loads(json.dumps(to_jsonable(original)))
    restored = from_dict(SiteSnapshot, payload)
    assert to_jsonable(restored) == to_jsonable(original)
    assert restored.pages[0].og.title == "Naslov"
    assert restored.home is restored.pages[0]


def test_unknown_fields_are_ignored():
    """An older snapshot on disk must not crash newer code."""
    payload = to_jsonable(_snapshot())
    payload["field_from_the_future"] = 1
    assert from_dict(SiteSnapshot, payload).domain == "d.rs"


def test_unknown_without_a_reason_is_a_bug():
    with pytest.raises(ValueError, match="unknown"):
        CheckResult(check_id="seo.title.missing", status="unknown")


def test_finding_without_findings_is_a_bug():
    with pytest.raises(ValueError, match="without a single finding"):
        CheckResult(check_id="seo.title.missing", status="finding")


def test_ok_with_a_finding_is_a_bug():
    finding = Finding(
        domain="d.rs",
        check_id="seo.title.missing",
        level=1,
        category="seo",
        severity="high",
    )
    with pytest.raises(ValueError, match="status is not"):
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
