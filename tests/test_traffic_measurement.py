"""The browser's network traffic counter (ADR-016), without a browser.

Every weight finding stands on the decision "measured / unmeasured / skipped": unmeasured counted
as zero is exactly the Performance API error the module docstring of `fetch.browser` describes,
and skipped counted as unmeasured falsely pushes the measurement to `unknown`. A decision table
over one response: URL kind × status × body × content-length.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from sitetriage.fetch.browser import CONSOLE_SAMPLES, _Recorder, _resource_type


class FakeResponse:
    """A fake Playwright response with only what the counter reads."""

    def __init__(
        self,
        url: str = "https://d.rs/slika.png",
        status: int = 200,
        body: bytes = b"x" * 1000,
        headers: dict[str, str] | None = None,
        kind: str = "image",
        body_error: Exception | None = None,
        hangs: bool = False,
    ) -> None:
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.request = SimpleNamespace(resource_type=kind, sizes=self._sizes)
        self._body, self._error, self._hangs = body, body_error, hangs

    async def _sizes(self) -> dict[str, int]:
        """`body` is what was transferred over the network (BUG-016)."""
        if self._hangs:
            await asyncio.Event().wait()
        if self._error:
            raise self._error
        return {"responseBodySize": len(self._body)}


def measure(*responses: FakeResponse, timeout: float = 1.0) -> _Recorder:
    async def run() -> _Recorder:
        counter = _Recorder()
        for response in responses:
            counter.on_response(response)
        await counter.drain(timeout)
        return counter

    return asyncio.run(run())


ERROR = RuntimeError("body not available (from cache or aborted)")


@pytest.mark.parametrize(
    "response, total_bytes, unmeasured",
    [
        pytest.param(FakeResponse(url="data:image/png;base64,AAA"), 0, 0, id="tab-data-skipped"),
        pytest.param(FakeResponse(url="blob:https://d.rs/1"), 0, 0, id="tab-blob-skipped"),
        pytest.param(FakeResponse(status=301), 0, 0, id="tab-redirect-skipped"),
        pytest.param(FakeResponse(status=399), 0, 0, id="gv-399-redirect"),
        pytest.param(FakeResponse(status=204, body=b""), 0, 0, id="tab-204-is-zero-not-unmeasured"),
        pytest.param(FakeResponse(status=304, body=b""), 0, 0, id="tab-304-is-zero-not-unmeasured"),
        pytest.param(FakeResponse(status=200), 1000, 0, id="tab-body-read"),
        pytest.param(FakeResponse(status=400), 1000, 0, id="gv-400-body-counts"),
        pytest.param(
            FakeResponse(body_error=ERROR, headers={"content-length": "500"}), 500, 0,
            id="tab-no-body-with-length",
        ),
        pytest.param(FakeResponse(body_error=ERROR), 0, 1, id="tab-no-body-no-length"),
        pytest.param(
            FakeResponse(body_error=ERROR, headers={"content-length": "abc"}), 0, 1, id="nv-length-text"
        ),
        pytest.param(
            FakeResponse(body_error=ERROR, headers={"content-length": "-5"}), 0, 1, id="nv-length-negative"
        ),
        pytest.param(FakeResponse(hangs=True), 0, 1, id="tab-body-does-not-arrive-in-time"),
    ],
)
def test_decision_for_one_response(response, total_bytes, unmeasured):
    counter = measure(response, timeout=0.2)
    assert counter.total_bytes == total_bytes
    assert counter.unmeasured == unmeasured


def test_bytes_add_up_by_type():
    counter = measure(
        FakeResponse(url="https://d.rs/a.png", kind="image", body=b"x" * 300),
        FakeResponse(url="https://d.rs/b.png", kind="image", body=b"x" * 200),
        FakeResponse(url="https://d.rs/v.mp4", kind="media", body=b"x" * 5000),
        FakeResponse(url="https://d.rs/api", kind="xhr", body=b"x" * 50),
    )
    assert counter.by_type == {"image": 500, "media": 5000, "other": 50}
    assert counter.total_bytes == 5550
    assert counter.bytes_by_url["https://d.rs/v.mp4"] == 5000


def test_phase_is_recorded_when_the_request_starts():
    """ADR-016: the body of a request started before `load` counts "until load" even when it arrives later."""
    before = FakeResponse(url="https://d.rs/pre.js", kind="script", body=b"x" * 300)
    hangs = FakeResponse(url="https://d.rs/strim", kind="media", hangs=True)
    after = FakeResponse(url="https://d.rs/chat.js", kind="script", body=b"x" * 200)

    async def run() -> _Recorder:
        counter = _Recorder()
        counter.on_request(before.request)
        counter.on_request(hangs.request)
        counter.on_load(None)
        counter.on_request(after.request)
        for response in (before, hangs, after):
            counter.on_response(response)
        await counter.drain(0.2)
        return counter

    counter = asyncio.run(run())
    assert (counter.requests_at_load, counter.request_count) == (2, 3)
    assert (counter.bytes_at_load, counter.total_bytes) == (300, 500)
    assert counter.by_type_at_load == {"script": 300}
    assert (counter.unmeasured_at_load, counter.unmeasured) == (1, 1)


def test_resource_type_that_cannot_be_read_is_other():
    class WithoutRequest:
        @property
        def request(self):
            raise RuntimeError("request not available")

    assert _resource_type(WithoutRequest()) == "other"


def test_console_counts_everything_but_keeps_only_the_first_five_samples():
    counter = _Recorder()
    for i in range(7):
        counter.on_console(SimpleNamespace(type="error", text=f"error {i}"))
    counter.on_console(SimpleNamespace(type="warning", text="warning"))
    counter.on_console(SimpleNamespace(type="log", text="plain output"))
    counter.on_page_error(RuntimeError("uncaught error"))
    assert counter.console_errors == 8
    assert counter.console_warnings == 1
    assert len(counter.samples) == CONSOLE_SAMPLES == 5
    assert counter.samples[0] == "error 0"
