"""JSON report: a contract with a schema version, which does not change silently."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest
from factories import clean_browser

from sitetriage import pipeline
from sitetriage.checks import registry
from sitetriage.config import load_config
from sitetriage.messages import reason
from sitetriage.models import BrowserSnapshot, from_dict, to_jsonable
from sitetriage.report import json_out

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(files("sitetriage").joinpath("schema/report-3.json").read_text(encoding="utf-8"))


def test_json_report_matches_the_schema(tmp_path):
    result = pipeline.recheck(FIXTURES, load_config())
    path = json_out.write(tmp_path / "report.json", result)
    document = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(document, SCHEMA)
    assert list(document)[:2] == ["schema_version", "scanner_version"], "the version is at the top"


def test_json_has_no_sentences():
    """A sentence is built from the evidence in the reader's language; in the contract it would be
    in one language forever."""
    document = to_jsonable(pipeline.recheck(FIXTURES, load_config()))
    findings = [f for r in document["ranked"] for f in r["findings"]]
    assert findings and not [f for f in findings if {"message_client", "message_tech"} & set(f)]


def test_schema_rejects_an_unknown_field():
    """`additionalProperties: false`: a new field goes into the schema first, then into the output."""
    document = to_jsonable(pipeline.recheck(FIXTURES, load_config()))
    document["ranked"][0]["new_field"] = 1
    with pytest.raises(jsonschema.ValidationError, match="new_field"):
        jsonschema.validate(document, SCHEMA)


# --------------------------------------------------------------------------- #
# Snapshots from 1.x stay readable: list A was calibrated on them
# --------------------------------------------------------------------------- #
def _v1(browser: BrowserSnapshot) -> BrowserSnapshot:
    """A level 2 snapshot as version 1.0.0 wrote it: without the fields added in 2.0 (ADR-016)."""
    data = to_jsonable(browser)
    data["scanner_version"] = "1.0.0"
    for field in ("requests_at_load", "bytes_at_load", "bytes_by_type_at_load", "unmeasured_at_load"):
        del data["network"][field]
    return from_dict(BrowserSnapshot, data)


@pytest.mark.parametrize(
    "check_id, field",
    [
        ("perf.page.weight", "network.bytes_at_load"),
        ("perf.request.count", "network.requests_at_load"),
    ],
)
def test_v1_snapshot_gives_unknown_not_a_crash(check_id, field):
    """A default zero would be `ok` for a weight nobody measured."""
    browser = _v1(clean_browser())
    ctx = registry.Context(domain=browser.domain, industry="other", config=load_config())
    result = {r.check_id: r for r in registry.run(2, browser, ctx)}[check_id]
    assert result.status == "unknown"
    assert reason(result.reason) == f"snapshot iz verzije 1.0.0 nema {field}"
