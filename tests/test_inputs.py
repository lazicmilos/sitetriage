"""Lista domena i CSV iz Excel-a (§4.1). Lista najčešće stiže iz Excel-a, a operater nije nužno programer."""

from __future__ import annotations

import pytest

from skener.inputs import InputError, is_excluded, read_domain_list, read_excel_csv, read_exclusions


def procitaj(sadrzaj: str | bytes):
    data = sadrzaj.encode("utf-8") if isinstance(sadrzaj, str) else sadrzaj
    return read_domain_list(data, "d.csv")


def test_cita_csv_sa_zaglavljem():
    rows, _ = procitaj(
        "domain,industry,note\ninstitucija.example,institucija,beleska\nrestoran-ugao.example,,\nklinika.example,NEPOSTOJECA,\n\n"
    )
    assert [r.domain for r in rows] == ["institucija.example", "restoran-ugao.example", "klinika.example"]
    assert rows[0].industry == "institucija" and rows[0].note == "beleska"
    assert rows[1].industry == "ostalo", "prazna delatnost pada na `ostalo` (§4.1)"
    assert rows[2].industry == "ostalo", "nepoznata delatnost pada na `ostalo`, ne ruši prolaz"


def test_csv_bez_kolone_domain_puca_razumljivo():
    with pytest.raises(InputError, match="red 1: nedostaje kolona `domain`"):
        procitaj("sajt,industry\na.rs,hotel\n")


@pytest.mark.parametrize(
    "sadrzaj",
    [
        pytest.param(b"", id="nv-prazan-fajl"),
        pytest.param(b"domain,industry\n", id="nv-samo-zaglavlje"),
        pytest.param(b"domain,industry\n\n  \n", id="nv-prazni-redovi"),
    ],
)
def test_csv_bez_domena_puca_razumljivo(sadrzaj):
    with pytest.raises(InputError):
        procitaj(sadrzaj)


# --------------------------------------------------------------------------- #
# Pogađanje grešaka: lista iz Excel-a na srpskom Windows-u
# --------------------------------------------------------------------------- #
def test_csv_iz_excela_sa_tackom_zarezom():
    """Srpska podešavanja Windows-a: Excel „CSV" razdvaja kolone sa `;`."""
    rows, _ = procitaj("domain;industry;note\ninstitucija.example;institucija;beleška\n")
    assert [(r.domain, r.industry, r.note) for r in rows] == [
        ("institucija.example", "institucija", "beleška")
    ]


def test_csv_u_windows_1250():
    """Excel bez „UTF-8" opcije čuva u windows-1250; ranije je ovo bio traceback."""
    csv = "domain,industry,note\ninstitucija.example,institucija,čćžšđ\n"
    rows, upozorenja = procitaj(csv.encode("cp1250"))
    assert rows[0].note == "čćžšđ"
    assert "windows-1250" in upozorenja[0].message


def test_csv_duplikati_se_skeniraju_jednom():
    """Isti domen dva puta = dva puta tuđ sajt i dva reda u izveštaju sa istim snapshotom."""
    rows, _ = procitaj(
        "domain,industry\ninstitucija.example,institucija\nINSTITUCIJA.EXAMPLE,hotel\n"
        "restoran-ugao.example,restoran\n"
    )
    assert [r.domain for r in rows] == ["institucija.example", "restoran-ugao.example"]
    assert rows[0].industry == "institucija", "važi prvo pojavljivanje"


def test_csv_sa_bom_oznakom():
    rows, _ = procitaj("domain,industry\ninstitucija.example,institucija\n".encode("utf-8-sig"))
    assert [r.domain for r in rows] == ["institucija.example"]


# --------------------------------------------------------------------------- #
# Broj reda: po njemu korisnik nađe red u Excel-u
# --------------------------------------------------------------------------- #
def test_upozorenje_nosi_broj_reda_i_domen():
    _, upozorenja = procitaj(
        "domain,industry\ninstitucija.example,institucija\nrestoran-ugao.example,picerija\n"
        "INSTITUCIJA.EXAMPLE,hotel\n"
    )
    assert [(u.row, u.domain) for u in upozorenja] == [
        (3, "restoran-ugao.example"),
        (4, "INSTITUCIJA.EXAMPLE"),
    ]


@pytest.mark.parametrize(
    ("sadrzaj", "redovi"),
    [
        pytest.param(b"domain\na.rs\nb.rs\n", [2, 3], id="ke-obican"),
        pytest.param(b"domain\na.rs\n\nb.rs\n", [2, 4], id="pg-prazan-red-se-broji"),
        pytest.param(b'domain,note\na.rs,"prvi\ndrugi"\nb.rs,x\n', [2, 3], id="pg-prelom-u-celiji"),
    ],
)
def test_broj_reda_je_red_u_excelu(sadrzaj, redovi):
    """Prazan red Excel prikazuje; ćelija sa prelomom je u fajlu dve linije, a u Excel-u jedan red."""
    assert [broj for broj, _ in read_excel_csv(sadrzaj, "d.csv").rows] == redovi


def test_zaglavlje_posle_praznog_reda():
    tabela = read_excel_csv(b"\ndomain;industry\na.rs;hotel\n", "d.csv")
    assert tabela.header_row == 2 and tabela.rows == [(3, {"domain": "a.rs", "industry": "hotel"})]


# --------------------------------------------------------------------------- #
# Izuzeti domeni (opt-out)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("domen", "izuzet"),
    [
        pytest.param("x.rs", True, id="ke-isti-host"),
        pytest.param("www.x.rs", True, id="ke-www"),
        pytest.param("blog.x.rs", True, id="ke-poddomen"),
        pytest.param("https://shop.x.rs/putanja", True, id="ke-pun-url"),
        pytest.param("X.RS", True, id="pg-velika-slova"),
        pytest.param("x.rs.", True, id="pg-tacka-na-kraju"),
        pytest.param("nex.rs", False, id="gv-sufiks-bez-tacke"),
        pytest.param("x.rs.zlo.com", False, id="pg-x.rs-na-pocetku-tudjeg-domena"),
        pytest.param("y.rs", False, id="ke-drugi-domen"),
    ],
)
def test_izuzece_vazi_za_poddomene(domen, izuzet):
    assert is_excluded(domen, ["x.rs"]) is izuzet


def test_co_rs_nije_izuzet_kad_je_izuzeta_firma_co_rs():
    """Bez Public Suffix liste „registrovani domen" od `firma.co.rs` bi bio `co.rs`."""
    izuzeti = ["firma.co.rs"]
    assert is_excluded("firma.co.rs", izuzeti) and is_excluded("www.firma.co.rs", izuzeti)
    assert not is_excluded("co.rs", izuzeti) and not is_excluded("druga.co.rs", izuzeti)


def test_www_u_unosu_izuzima_celu_firmu():
    assert is_excluded("x.rs", ["www.x.rs"]) and is_excluded("blog.x.rs", ["https://www.x.rs/"])


def test_fajl_sa_izuzetim_domenima():
    data = "\ufeffx.rs\n\n# ko je tražio i kada\ny.rs  # posle tarabe je komentar\n   \n".encode()
    assert read_exclusions(data) == ["x.rs", "y.rs"]
    assert not is_excluded("x.rs", read_exclusions(b"# samo komentar\n"))


def test_fajl_sa_izuzetim_domenima_u_windows_1250():
    """pg-: Notepad na srpskom Windows-u čuva komentar u windows-1250, a domen se svejedno čita."""
    assert read_exclusions("# tražio vlasnik iz Niša\nx.rs\n".encode("cp1250")) == ["x.rs"]
