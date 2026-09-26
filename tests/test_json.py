"""JSON izveštaj: ugovor sa verzijom šeme, koji se ne menja tiho."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest
from factories import clean_browser

from skener import pipeline
from skener.checks import registry
from skener.config import load_config
from skener.messages import reason
from skener.models import BrowserSnapshot, from_dict, to_jsonable
from skener.report import json_out

FIXTURES = Path(__file__).parent / "fixtures"
SEMA = json.loads(files("skener").joinpath("schema/report-2.json").read_text(encoding="utf-8"))


def test_json_izvestaj_prolazi_semu(tmp_path):
    rezultat = pipeline.recheck(FIXTURES, load_config())
    path = json_out.write(tmp_path / "report.json", rezultat)
    dokument = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(dokument, SEMA)
    assert list(dokument)[:2] == ["schema_version", "scanner_version"], "verzija je na vrhu dokumenta"


def test_json_nema_recenica():
    """Rečenica se pravi iz dokaza na jeziku čitaoca; u ugovoru bi bila na jednom jeziku zauvek."""
    dokument = to_jsonable(pipeline.recheck(FIXTURES, load_config()))
    nalazi = [f for r in dokument["ranked"] for f in r["findings"]]
    assert nalazi and not [f for f in nalazi if {"message_client", "message_tech"} & set(f)]


def test_sema_odbija_nepoznato_polje():
    """`additionalProperties: false`: novo polje mora prvo u šemu, pa tek onda u izlaz."""
    dokument = to_jsonable(pipeline.recheck(FIXTURES, load_config()))
    dokument["ranked"][0]["novo_polje"] = 1
    with pytest.raises(jsonschema.ValidationError, match="novo_polje"):
        jsonschema.validate(dokument, SEMA)


# --------------------------------------------------------------------------- #
# Snapshoti iz 1.x ostaju čitljivi: na njima je kalibrisana lista A
# --------------------------------------------------------------------------- #
def _v1(browser: BrowserSnapshot) -> BrowserSnapshot:
    """Snimak nivoa 2 kakav je zapisivala verzija 1.0.0: bez polja uvedenih u v2 (Z-24)."""
    podaci = to_jsonable(browser)
    podaci["scanner_version"] = "1.0.0"
    for polje in ("requests_at_load", "bytes_at_load", "bytes_by_type_at_load", "unmeasured_at_load"):
        del podaci["network"][polje]
    return from_dict(BrowserSnapshot, podaci)


@pytest.mark.parametrize(
    "check_id, polje",
    [
        ("perf.page.weight", "network.bytes_at_load"),
        ("perf.request.count", "network.requests_at_load"),
    ],
)
def test_v1_snapshot_daje_unknown_a_ne_pad(check_id, polje):
    """Podrazumevana nula bi bila `ok` za težinu koju niko nije izmerio."""
    browser = _v1(clean_browser())
    ctx = registry.Context(domain=browser.domain, industry="ostalo", config=load_config())
    rezultat = {r.check_id: r for r in registry.run(2, browser, ctx)}[check_id]
    assert rezultat.status == "unknown"
    assert reason(rezultat.reason) == f"snapshot iz verzije 1.0.0 nema {polje}"
