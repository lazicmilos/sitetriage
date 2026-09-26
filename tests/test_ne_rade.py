"""Z-20: sajt koji se ne otvara ide u listu „Ne rade", a ne u rangiranje.

`unreachable` se dodeljuje samo kad je stanje sigurno, i to posle dva pokušaja u razmaku od
bar `http.second_attempt_after_s`: ime ne postoji u DNS-u, ili TCP veza nije uspostavljena ni
na https ni na http. Sve ostalo je `failed`, jer sajt možda radi, samo ga mi nismo videli.
"""

from __future__ import annotations

import asyncio
import csv
import socket
import struct
import threading
import time

import httpcore
import httpx
import jsonschema
import pytest
from factories import clean_site
from localserver import html
from test_json import SEMA

from skener import pipeline, store
from skener.config import load_config
from skener.fetch import http
from skener.fetch.http import Outcome, _classify
from skener.messages import reason, render
from skener.models import DomainInput, Entry, SnapshotError, to_jsonable
from skener.report import csv_out, html_out
from skener.score import analyze

DOMEN = "ne-rade.test"
ISHODI = {
    "nxdomain": ("dns_nxdomain", "[Errno -2] Name or service not known"),
    "bez_adrese": ("dns_nodata", "[Errno -5] No address associated with hostname"),
    "dns_privremeno": ("dns_temporary", "[Errno -3] Temporary failure in name resolution"),
    "bez_veze": ("no_connection", "[Errno 111] Connection refused"),
    "rukovanje": ("tls_handshake", "[SSL: UNEXPECTED_EOF_WHILE_READING]"),
    "blokada": ("blocked", "adresa nije javna: ne-rade.test → 10.0.0.5"),
}


def _prolaz(monkeypatch, tabela: dict, *, posle_s: float = 0.0):
    """`scan_domains` nad jednim domenom, sa pravim redosledom pokušaja.

    `tabela[(pokušaj, šema)]` je ishod zahteva za početnu: ime iz `ISHODI` ili HTTP status.
    Čega nema u tabeli, vraća 200. Vraća snapshot i (početak, kraj) svakog pokušaja.
    """
    monkeypatch.setattr("skener.fetch.http.random.uniform", lambda *_: 0)
    pokusaji: list[tuple[float, float]] = []
    pravi = http.fetch_site

    class PoTabeli(http.Fetcher):
        pokusaj = 0

        async def _send(self, url: str, *, verify: bool) -> Outcome:
            if url not in (f"https://{DOMEN}/", f"http://{DOMEN}/"):
                return Outcome(url=url, status=404, final_url=url, redirect_chain=[url], body=b"")
            ishod = tabela.get((self.pokusaj, url.split("://")[0]), 200)
            if isinstance(ishod, str):
                return Outcome(url=url, error_kind=ISHODI[ishod][0], error_detail=ISHODI[ishod][1])
            return Outcome(url=url, status=ishod, final_url=url, redirect_chain=[url], body=html("Početna"))

    async def brojac(fetcher, target):
        fetcher.pokusaj += 1
        pocetak = time.monotonic()
        snapshot = await pravi(fetcher, target)
        pokusaji.append((pocetak, time.monotonic()))
        return snapshot

    monkeypatch.setattr(http, "Fetcher", PoTabeli)
    monkeypatch.setattr(http, "fetch_site", brojac)
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["http"]["second_attempt_after_s"] = posle_s
    [snapshot] = asyncio.run(http.scan_domains([DomainInput(DOMEN)], cfg))
    return snapshot, pokusaji


def _oba(sema: str, ishod) -> dict:
    return {(1, sema): ishod, (2, sema): ishod}


# --------------------------------------------------------------------------- #
# Tabela iz Z-20: šta je `unreachable`, a šta `failed`
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "tabela, status, razlog, pokusaja",
    [
        pytest.param(_oba("https", "nxdomain"), "unreachable", "dns", 2, id="tab-ime-ne-postoji"),
        pytest.param(_oba("https", "bez_adrese"), "unreachable", "dns", 2, id="tab-ime-bez-adrese"),
        pytest.param(
            {**_oba("https", "bez_veze"), **_oba("http", "bez_veze")},
            "unreachable", "no_response", 2, id="tab-bez-veze-na-https-i-http",
        ),
        pytest.param(_oba("https", "dns_privremeno"), "failed", None, 1, id="tab-dns-privremeno"),
        pytest.param(
            {**_oba("https", "rukovanje"), **_oba("http", "bez_veze")},
            "failed", None, 1, id="tab-tls-rukovanje-a-http-ne-radi",
        ),
        pytest.param(
            {**_oba("https", "bez_veze"), **_oba("http", 403)}, "failed", None, 1, id="tab-http-odgovor-403"
        ),
        pytest.param(_oba("https", 503), "failed", None, 1, id="tab-http-odgovor-503"),
        pytest.param(_oba("https", "blokada"), "failed", None, 1, id="tab-ssrf-blokada"),
    ],
)
def test_ne_radi_samo_kad_je_sigurno(monkeypatch, tabela, status, razlog, pokusaja):
    snapshot, pokusaji = _prolaz(monkeypatch, tabela)
    izvestaj = analyze(snapshot, load_config())
    assert izvestaj.status == status
    assert len(pokusaji) == pokusaja == len(snapshot.entry_attempts)
    nalazi = [f for f in izvestaj.findings if f.check_id == "infra.unreachable"]
    if razlog is None:
        assert not nalazi and izvestaj.reason is not None, "`failed` ima razlog za listu „Nije skenirano”"
        return
    [nalaz] = nalazi
    assert nalaz.severity == "critical" and nalaz.category == "infra"
    assert nalaz.evidence["razlog"] == razlog and nalaz.evidence["broj_pokusaja"] == 2
    assert [nalaz.evidence["prvi_pokusaj"], nalaz.evidence["drugi_pokusaj"]] == snapshot.entry_attempts
    assert all(t.endswith("Z") for t in snapshot.entry_attempts)


def test_drugi_pokusaj_koji_uspe_skenira_sajt_normalno(monkeypatch):
    snapshot, pokusaji = _prolaz(monkeypatch, {(1, "https"): "nxdomain"})
    izvestaj = analyze(snapshot, load_config())
    assert len(pokusaji) == 2
    assert snapshot.entry.status == 200 and snapshot.robots.status == 404, "posle ulaza ide ceo prolaz"
    assert izvestaj.status in ("scanned", "partial")
    assert "infra.unreachable" not in {f.check_id for f in izvestaj.findings}


def test_drugi_pokusaj_ceka_najmanje_zadato_vreme(monkeypatch):
    _, pokusaji = _prolaz(monkeypatch, _oba("https", "nxdomain"), posle_s=0.3)
    (_, kraj_prvog), (pocetak_drugog, _) = pokusaji
    assert pocetak_drugog - kraj_prvog >= 0.3


@pytest.mark.parametrize(
    "errno, vrsta",
    [
        pytest.param(socket.EAI_NONAME, "dns_nxdomain", id="ke-ime-ne-postoji"),
        pytest.param(
            socket.EAI_NODATA,
            "dns_nodata",
            id="ke-ime-bez-adrese",
            marks=pytest.mark.skipif(socket.EAI_NODATA == socket.EAI_NONAME, reason="na Windows-u isti kod"),
        ),
        pytest.param(socket.EAI_AGAIN, "dns_temporary", id="ke-privremeno"),
        pytest.param(socket.EAI_FAIL, "dns", id="ke-ostalo"),
    ],
)
def test_dns_greska_se_razvrstava_po_errno(errno, vrsta):
    """Poredi se sa konstantama iz `socket`: brojevi su drugačiji na Linux-u i Windows-u."""
    try:
        try:
            raise socket.gaierror(errno, "dns")
        except socket.gaierror as cause:
            raise httpx.ConnectError("greška", request=None) from cause
    except httpx.ConnectError as exc:
        assert _classify(exc)[0] == vrsta


def test_eai_again_nije_unreachable(monkeypatch):
    async def privremeno(host, port):
        raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")

    monkeypatch.setattr(http, "_razresi", privremeno)
    cfg = load_config()
    cfg["http"]["second_attempt_after_s"] = 0
    [snapshot] = asyncio.run(http.scan_domains([DomainInput(DOMEN)], cfg))
    izvestaj = analyze(snapshot, cfg)
    assert snapshot.entry.error_kind == "dns_temporary"
    assert len(snapshot.entry_attempts) == 1, "privremen DNS ne izgleda kao sajt koji ne radi"
    assert izvestaj.status == "failed"
    assert "DNS privremeno nedostupan" in reason(izvestaj.reason, "sr")


# --------------------------------------------------------------------------- #
# Prekid posle uspostavljene TCP veze nije „bez veze": server je tu, samo ne nama (BUG-004)
# --------------------------------------------------------------------------- #
class ZatvaraVezu:
    """Prihvata TCP vezu i odmah je zatvara, pre TLS-a; `reset` šalje RST umesto FIN."""

    def __init__(self, *, reset: bool) -> None:
        self.reset = reset
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._radi, daemon=True).start()

    def _radi(self) -> None:
        while True:
            try:
                veza, _ = self.sock.accept()
            except OSError:
                return
            if self.reset:
                veza.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            veza.close()


def _ulaz(domen: str, dozvoljeno: str):
    cfg = load_config()
    cfg["http"]["delay_ms"] = [0, 0]
    cfg["net"]["allowed_private"] = [dozvoljeno]

    async def run():
        async with http.Fetcher(cfg) as fetcher:
            return await http.fetch_site(fetcher, DomainInput(domen))

    return asyncio.run(run())


@pytest.mark.parametrize("reset", [False, True], ids=["st-zatvara", "st-resetuje"])
def test_prekinuto_tls_rukovanje_nije_unreachable(reset):
    server = ZatvaraVezu(reset=reset)
    try:
        snapshot = _ulaz(f"https://127.0.0.1:{server.port}", f"127.0.0.1:{server.port}")
    finally:
        server.sock.close()
    assert snapshot.entry.status is None
    assert snapshot.entry.error_kind != "no_connection", snapshot.entry.error_detail
    assert snapshot.entry_unreachable() is None


@pytest.mark.parametrize(
    "greska, uzrok, bez_veze",
    [
        # RST ume da stigne pre nego što `connect` vrati; i tada je server prihvatio vezu.
        pytest.param(httpcore.ConnectError("x"), ConnectionResetError(104, "reset"), False, id="st-reset"),
        pytest.param(httpcore.ConnectTimeout(""), None, True, id="st-istek"),
    ],
)
def test_tcp_greska_koja_jeste_i_nije_bez_veze(monkeypatch, greska, uzrok, bez_veze):
    greska.__cause__ = uzrok

    async def javna(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    class Pada(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, **_kwargs):
            raise greska

    monkeypatch.setattr(http, "_razresi", javna)
    backend = http._JavneAdrese(Pada(), frozenset())
    with pytest.raises(httpcore.ConnectError) as uhvacena:
        asyncio.run(backend.connect_tcp("primer.rs", 443))
    assert isinstance(uhvacena.value, http.NoConnection) is bez_veze


def test_odbijena_tcp_veza_je_bez_veze():
    with socket.create_server(("127.0.0.1", 0)) as zauzet:
        port = zauzet.getsockname()[1]
    snapshot = _ulaz(f"http://127.0.0.1:{port}", f"127.0.0.1:{port}")
    assert snapshot.entry.error_kind == "no_connection"


# --------------------------------------------------------------------------- #
# Izveštaji: „Ne rade" posle rangiranja, „Nije skenirano" sa razlogom
# --------------------------------------------------------------------------- #
def _ne_radi(domain: str = "ugasen.rs", razlog: str = "dns"):
    pokusaji = ["2026-09-22T09:00:00Z", "2026-09-22T09:01:05Z"]
    site = clean_site(domain=domain, pages=[], entry_attempts=pokusaji)
    vrsta = "dns_nxdomain" if razlog == "dns" else "no_connection"
    site.entry = Entry(requested_url=f"https://{domain}/", error_kind=vrsta, error_detail="detalj")
    if razlog == "no_response":
        site.errors = [SnapshotError("entry", "no_connection", "refused")] * 2
    return site


def _ne_skeniran(domain: str = "zatvoren.rs"):
    site = clean_site(domain=domain)
    site.entry.status = 403
    site.pages[0].status = 403
    return site


def test_v1_snapshot_bez_odgovora_je_unknown():
    """Snapshot iz 1.x nema drugi pokušaj ni vrstu DNS greške: ne zna se, a ne „radi"."""
    site = _ne_radi()
    site.scanner_version = "1.0.0"
    site.entry.error_kind = "dns"
    izvestaj = analyze(site, load_config())
    assert izvestaj.status == "failed"
    [nepoznat] = [u for u in izvestaj.unknowns if u.check_id == "infra.unreachable"]
    assert nepoznat.reason.code == "v1_snapshot"


@pytest.mark.parametrize(
    "izmena, kod",
    [
        pytest.param(lambda s: setattr(s, "entry", None), "entry_missing", id="ke-nema-ulaza"),
        pytest.param(lambda s: setattr(s.entry, "status", 403), "entry_status", id="ke-http-status"),
        pytest.param(lambda s: setattr(s.entry, "error_kind", "blocked"), "entry_error", id="ke-greska"),
    ],
)
def test_nije_skenirano_ima_razlog(izmena, kod):
    site = clean_site(pages=[])
    site.entry.status = None
    izmena(site)
    izvestaj = analyze(site, load_config())
    assert izvestaj.status == "failed" and izvestaj.reason.code == kod
    assert "{" not in reason(izvestaj.reason, "en")


def test_unreachable_nije_u_rangiranju(tmp_path):
    for site in (_ne_radi(), _ne_skeniran(), clean_site(domain="radi.rs")):
        store.write_site(tmp_path, site)
    rezultat = pipeline.recheck(tmp_path, load_config())
    assert [r.domain for r in rezultat.ranked] == ["radi.rs"] and rezultat.ranked[0].rank == 1
    assert [r.domain for r in rezultat.unreachable] == ["ugasen.rs"]
    assert [r.domain for r in rezultat.not_scanned] == ["zatvoren.rs"]
    assert rezultat.summary["unreachable"] == 1 and rezultat.summary["failed"] == 1
    assert rezultat.unreachable[0].rank == 0 and rezultat.not_scanned[0].rank == 0
    jsonschema.validate(to_jsonable(rezultat), SEMA)


@pytest.mark.parametrize(
    "razlog, lang, ocekivano",
    [
        pytest.param("dns", "sr", "2 pokušaja", id="sr-dns-broj"),
        pytest.param("dns", "sr", "domen nema zapis koji ga povezuje sa serverom", id="sr-dns"),
        pytest.param("dns", "en", "2 attempts", id="en-dns-broj"),
        pytest.param("dns", "en", "the domain has no record that connects it to a server", id="en-dns"),
        pytest.param("no_response", "sr", "ni preko https ni preko http", id="sr-bez-odgovora"),
        pytest.param("no_response", "en", "over neither https nor http", id="en-bez-odgovora"),
    ],
)
def test_recenica_navodi_kad_koliko_puta_i_sta_se_desilo(razlog, lang, ocekivano):
    nalaz = analyze(_ne_radi(razlog=razlog), load_config()).findings[0]
    poruka = render(nalaz, lang).client
    assert ocekivano in poruka, poruka
    assert "2026-09-22 09:00" in poruka and "2026-09-22 09:01" in poruka, poruka


def test_html_ima_odeljke_ne_rade_i_nije_skenirano():
    config = load_config()
    izvestaji = [analyze(s, config) for s in (clean_site(domain="radi.rs"), _ne_radi(), _ne_skeniran())]
    stranica = html_out.render(izvestaji, config, excluded=2)

    def odeljak(naslov: str) -> int:
        return stranica.index(f"<h2>{naslov}</h2>")

    rangirano, ne_rade = odeljak("Rangirani domeni"), odeljak("Ne rade")
    nije_skenirano, po_domenu = odeljak("Nije skenirano"), odeljak("Po domenu")
    assert rangirano < ne_rade < nije_skenirano < po_domenu
    assert "ugasen.rs" not in stranica[rangirano:ne_rade] + stranica[po_domenu:], "nije u rangiranju"
    assert "ugasen.rs" in stranica[ne_rade:nije_skenirano]
    nije = stranica[nije_skenirano:po_domenu]
    assert "zatvoren.rs" in nije and "početna je vratila status 403" in nije
    assert "Izuzeto na zahtev administratora: 2" in nije


def test_nacrt_mejla_za_sajt_koji_ne_radi_je_poseban():
    izvestaj = analyze(_ne_radi(), load_config())
    nacrt = html_out.email_draft(izvestaj)
    assert "primetio sledeće" not in nacrt
    assert "ugasen.rs" in nacrt and "domen nema zapis koji ga povezuje sa serverom" in nacrt


def test_summary_csv_ima_sve_domene_sa_statusom(tmp_path):
    config = load_config()
    izvestaji = [analyze(s, config) for s in (clean_site(domain="radi.rs"), _ne_radi(), _ne_skeniran())]
    putanja = csv_out.write_summary(tmp_path / "summary.csv", izvestaji)
    redovi = {r["domain"]: r["status"] for r in csv.DictReader(putanja.open(encoding="utf-8"))}
    assert redovi == {"radi.rs": "scanned", "ugasen.rs": "unreachable", "zatvoren.rs": "failed"}
