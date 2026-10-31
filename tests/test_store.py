"""Snapshot folders on disk: one folder per domain, and `recheck` reads every one back.

BUG-03: `slug()` only cleaned the name, so two different domain strings could share a folder
and the second silently overwrote the first.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest
from factories import clean_browser, clean_site
from localserver import FakeSite

from sitetriage import store
from sitetriage.config import load_config
from sitetriage.fetch.http import scan_domains
from sitetriage.models import DomainInput, to_jsonable

SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._~-]*$")


@pytest.mark.parametrize(
    "first, second",
    [
        ("http://127.0.0.1:18001", "http://127.0.0.1:18001/"),
        ("localhost", "localhost."),
        ("[::1]", "1"),
        ("Localhost", "localhost"),
        ("a_b.example", "a b.example"),
        ("", "unknown-domain"),
    ],
    ids=["pg-trailing-slash", "pg-trailing-dot", "pg-ipv6-brackets", "pg-case", "pg-replaced-char",
         "pg-empty-vs-fallback-name"],
)
def test_distinct_domains_get_distinct_folders(first, second):
    assert store.slug(first) != store.slug(second)


@pytest.mark.parametrize(
    "domain",
    ["institucija.example", "b2b-firma.example", "localhost", "127.0.0.1"],
    ids=["ke-plain", "ke-hyphen", "ke-single-label", "ke-ipv4"],
)
def test_clean_domain_keeps_its_name_as_the_folder(domain):
    """Clean names stay as they were in 3.0.0, so existing snapshots and fixtures keep their folder."""
    assert store.slug(domain) == domain


@pytest.mark.parametrize(
    "domain",
    ["http://127.0.0.1:18001/", "[::1]", "../../etc/passwd", "..", "Ordinacija.Example", "~", " x "],
    ids=["ke-origin", "ke-ipv6", "nv-traversal", "nv-dotdot", "ke-upper", "nv-separator-only",
         "ke-spaces"],
)
def test_changed_name_is_readable_safe_and_stable(domain):
    name = store.slug(domain)
    assert SAFE_NAME.match(name) and "/" not in name and "\\" not in name and ".." not in name
    assert re.fullmatch(r".+~[0-9a-f]{8}", name)
    assert store.slug(domain) == name, "the same domain must land in the same folder in every run"


def test_pg_two_colliding_domains_both_come_back_from_read_all(tmp_path):
    """site.json of one domain and browser.json of another must never share a folder."""
    first, second = "http://127.0.0.1:18001", "http://127.0.0.1:18001/"
    store.write_site(tmp_path, clean_site(domain=first))
    store.write_site(tmp_path, clean_site(domain=second))
    store.write_browser(tmp_path, clean_browser(domain=first), compress=True)

    loaded = {site.domain: browser for site, browser in store.read_all(tmp_path)}
    assert set(loaded) == {first, second}
    assert loaded[first] is not None and loaded[first].domain == first
    assert loaded[second] is None


def test_pg_scan_of_two_spellings_of_one_origin_keeps_both_snapshots(tmp_path):
    with FakeSite() as site:
        cfg = load_config()
        cfg["http"]["delay_ms"] = [0, 0]
        targets = [DomainInput(domain=site.base_url), DomainInput(domain=site.base_url + "/")]
        scanned = asyncio.run(scan_domains(targets, cfg, snapshot_dir=tmp_path))

    assert len(scanned) == 2
    loaded = sorted(snapshot.domain for snapshot, _browser in store.read_all(tmp_path))
    assert loaded == sorted(t.domain for t in targets)


def test_st_folder_from_3_0_0_still_loads(tmp_path):
    """3.0.0 named the folder without a hash; `read_all` takes the domain from site.json."""
    domain = "http://127.0.0.1:18001/"
    folder = tmp_path / "http_127.0.0.1_18001"
    folder.mkdir()
    (folder / store.SITE_NAME).write_text(json.dumps(to_jsonable(clean_site(domain=domain))), "utf-8")

    [(site, browser)] = list(store.read_all(tmp_path))
    assert site.domain == domain and browser is None


def test_st_same_domain_overwrites_its_own_snapshot(tmp_path):
    store.write_site(tmp_path, clean_site(domain="cist.rs", industry="other"))
    store.write_site(tmp_path, clean_site(domain="cist.rs", industry="hotel"))
    [(site, _browser)] = list(store.read_all(tmp_path))
    assert site.industry == "hotel"


@pytest.mark.parametrize("compress", [False, True], ids=["pg-plain", "pg-gzip"])
def test_pg_snapshot_of_another_domain_is_never_overwritten(tmp_path, compress):
    """Defence in depth: a folder that already holds another domain is refused, not overwritten."""
    folder = tmp_path / store.slug("cist.rs")
    store.write_site(tmp_path, clean_site(domain="drugi.rs"), compress=compress)
    (tmp_path / "drugi.rs").rename(folder)

    with pytest.raises(store.SnapshotCollision, match="drugi.rs"):
        store.write_browser(tmp_path, clean_browser(domain="cist.rs"))
    [(site, browser)] = list(store.read_all(tmp_path))
    assert site.domain == "drugi.rs" and browser is None


def test_pg_unreadable_old_snapshot_is_overwritten(tmp_path):
    """A broken file from an interrupted run must not block a new run."""
    folder = tmp_path / "cist.rs"
    folder.mkdir()
    (folder / store.SITE_NAME).write_text("{not json", "utf-8")
    store.write_site(tmp_path, clean_site(domain="cist.rs"))
    [(site, _browser)] = list(store.read_all(tmp_path))
    assert site.domain == "cist.rs"
