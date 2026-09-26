"""Brojač mrežnog saobraćaja u browseru (§7.2), bez browsera.

Na odluci „izmereno / nemereno / preskočeno" stoji svaki nalaz o težini: nemereno
brojano kao nula je tačno greška koju spec opisuje kod Performance API-ja, a
preskočeno brojano kao nemereno lažno obara merenje u `unknown`. Tabela
odlučivanja nad jednim odgovorom: vrsta adrese × status × telo × content-length.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from skener.fetch.browser import CONSOLE_SAMPLES, _Recorder, _resource_type


class Odgovor:
    """Lažan Playwright odgovor sa samo onim što brojač čita."""

    def __init__(
        self,
        url: str = "https://d.rs/slika.png",
        status: int = 200,
        telo: bytes = b"x" * 1000,
        zaglavlja: dict[str, str] | None = None,
        vrsta: str = "image",
        greska_tela: Exception | None = None,
        visi: bool = False,
    ) -> None:
        self.url = url
        self.status = status
        self.headers = zaglavlja or {}
        self.request = SimpleNamespace(resource_type=vrsta, sizes=self._sizes)
        self._telo, self._greska, self._visi = telo, greska_tela, visi

    async def _sizes(self) -> dict[str, int]:
        """`telo` je ono što je preneto preko mreže (BUG-016)."""
        if self._visi:
            await asyncio.Event().wait()
        if self._greska:
            raise self._greska
        return {"responseBodySize": len(self._telo)}


def izmeri(*odgovori: Odgovor, rok: float = 1.0) -> _Recorder:
    async def run() -> _Recorder:
        brojac = _Recorder()
        for odgovor in odgovori:
            brojac.on_response(odgovor)
        await brojac.drain(rok)
        return brojac

    return asyncio.run(run())


GRESKA = RuntimeError("telo nije dostupno (iz keša ili prekinuto)")


@pytest.mark.parametrize(
    "odgovor, bajtova, nemereno",
    [
        pytest.param(Odgovor(url="data:image/png;base64,AAA"), 0, 0, id="tab-data-preskace-se"),
        pytest.param(Odgovor(url="blob:https://d.rs/1"), 0, 0, id="tab-blob-preskace-se"),
        pytest.param(Odgovor(status=301), 0, 0, id="tab-preusmerenje-preskace-se"),
        pytest.param(Odgovor(status=399), 0, 0, id="gv-399-preusmerenje"),
        pytest.param(Odgovor(status=204, telo=b""), 0, 0, id="tab-204-je-nula-a-ne-nemereno"),
        pytest.param(Odgovor(status=304, telo=b""), 0, 0, id="tab-304-je-nula-a-ne-nemereno"),
        pytest.param(Odgovor(status=200), 1000, 0, id="tab-telo-procitano"),
        pytest.param(Odgovor(status=400), 1000, 0, id="gv-400-telo-se-broji"),
        pytest.param(
            Odgovor(greska_tela=GRESKA, zaglavlja={"content-length": "500"}), 500, 0,
            id="tab-bez-tela-sa-duzinom",
        ),
        pytest.param(Odgovor(greska_tela=GRESKA), 0, 1, id="tab-bez-tela-bez-duzine"),
        pytest.param(
            Odgovor(greska_tela=GRESKA, zaglavlja={"content-length": "abc"}), 0, 1, id="nv-duzina-tekst"
        ),
        pytest.param(
            Odgovor(greska_tela=GRESKA, zaglavlja={"content-length": "-5"}), 0, 1, id="nv-duzina-negativna"
        ),
        pytest.param(Odgovor(visi=True), 0, 1, id="tab-telo-ne-stize-u-roku"),
    ],
)
def test_odluka_za_jedan_odgovor(odgovor, bajtova, nemereno):
    brojac = izmeri(odgovor, rok=0.2)
    assert brojac.total_bytes == bajtova
    assert brojac.unmeasured == nemereno


def test_bajtovi_se_sabiraju_po_vrsti():
    brojac = izmeri(
        Odgovor(url="https://d.rs/a.png", vrsta="image", telo=b"x" * 300),
        Odgovor(url="https://d.rs/b.png", vrsta="image", telo=b"x" * 200),
        Odgovor(url="https://d.rs/v.mp4", vrsta="media", telo=b"x" * 5000),
        Odgovor(url="https://d.rs/api", vrsta="xhr", telo=b"x" * 50),
    )
    assert brojac.by_type == {"image": 500, "media": 5000, "other": 50}
    assert brojac.total_bytes == 5550
    assert brojac.bytes_by_url["https://d.rs/v.mp4"] == 5000


def test_faza_se_belezi_kad_zahtev_pocne():
    """Z-24: telo zahteva započetog pre `load` pripada fazi „do load" i kad stigne posle nje."""
    pre = Odgovor(url="https://d.rs/pre.js", vrsta="script", telo=b"x" * 300)
    visi = Odgovor(url="https://d.rs/strim", vrsta="media", visi=True)
    posle = Odgovor(url="https://d.rs/chat.js", vrsta="script", telo=b"x" * 200)

    async def run() -> _Recorder:
        brojac = _Recorder()
        brojac.on_request(pre.request)
        brojac.on_request(visi.request)
        brojac.on_load(None)
        brojac.on_request(posle.request)
        for odgovor in (pre, visi, posle):
            brojac.on_response(odgovor)
        await brojac.drain(0.2)
        return brojac

    brojac = asyncio.run(run())
    assert (brojac.requests_at_load, brojac.request_count) == (2, 3)
    assert (brojac.bytes_at_load, brojac.total_bytes) == (300, 500)
    assert brojac.by_type_at_load == {"script": 300}
    assert (brojac.unmeasured_at_load, brojac.unmeasured) == (1, 1)


def test_vrsta_resursa_koja_se_ne_moze_procitati_je_other():
    class BezZahteva:
        @property
        def request(self):
            raise RuntimeError("zahtev nije dostupan")

    assert _resource_type(BezZahteva()) == "other"


def test_konzola_broji_sve_a_cuva_samo_prvih_pet_primera():
    brojac = _Recorder()
    for i in range(7):
        brojac.on_console(SimpleNamespace(type="error", text=f"greška {i}"))
    brojac.on_console(SimpleNamespace(type="warning", text="upozorenje"))
    brojac.on_console(SimpleNamespace(type="log", text="običan ispis"))
    brojac.on_page_error(RuntimeError("nehvatana greška"))
    assert brojac.console_errors == 8
    assert brojac.console_warnings == 1
    assert len(brojac.samples) == CONSOLE_SAMPLES == 5
    assert brojac.samples[0] == "greška 0"
