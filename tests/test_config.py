import pytest

from skener.config import ConfigError, _validate, digest, get, load_config, multiplier, user_agent


def test_ucitava_podrazumevanu_konfiguraciju():
    cfg = load_config()
    assert get(cfg, "thresholds.i18n.diacritic_ratio") == 0.005
    assert get(cfg, "severity_points.critical") == 40


def test_korisnicka_konfiguracija_se_spaja_a_ne_zamenjuje(tmp_path):
    override = tmp_path / "moj.toml"
    override.write_text("[thresholds.i18n]\nmin_text_length = 100\n", encoding="utf-8")
    cfg = load_config(override)
    assert get(cfg, "thresholds.i18n.min_text_length") == 100
    # ostali pragovi iz iste sekcije prezivljavaju spajanje
    assert get(cfg, "thresholds.i18n.diacritic_ratio") == 0.005
    assert get(cfg, "severity_points.critical") == 40


def test_mnozioci_i_fallback_na_ostalo():
    cfg = load_config()
    assert multiplier(cfg, "hotel", "social") == 1.5
    assert multiplier(cfg, "restoran", "perf") == 1.5
    assert multiplier(cfg, "zdravstvo", "a11y") == 1.5
    assert multiplier(cfg, "nepostojeca-delatnost", "seo") == 1.0


def test_nepostojeci_kljuc_puca_i_imenuje_se():
    cfg = load_config()
    with pytest.raises(ConfigError, match="thresholds.perf.nema_me"):
        get(cfg, "thresholds.perf.nema_me")


def test_parcijalni_mnozilac_ne_razbija_tabelu(tmp_path):
    """Spajanje je ono što čuva ostale kategorije kad korisnik prepiše jednu."""
    override = tmp_path / "moj.toml"
    override.write_text("[industry_multipliers.hotel]\nseo = 9.9\n", encoding="utf-8")
    cfg = load_config(override)
    assert multiplier(cfg, "hotel", "seo") == 9.9
    assert multiplier(cfg, "hotel", "social") == 1.5


def test_nepotpuna_tabela_mnozilaca_puca():
    """Prava granica: neko obriše red u samom skener.toml tokom kalibracije."""
    broken = {
        "severity_points": {"critical": 40, "high": 20, "medium": 8, "low": 3},
        "industry_multipliers": {"hotel": {"seo": 1.2}},
    }
    with pytest.raises(ConfigError, match="industry_multipliers.hotel.social"):
        _validate(broken)


# --------------------------------------------------------------------------- #
# Identitet operatera: User-Agent predstavlja onog ko skenira, ne autora alata.
# Alat se prodaje, pa bi inače svaki kupac skenirao sa autorovim mejlom.
# --------------------------------------------------------------------------- #
@pytest.fixture
def bez_okruzenja(monkeypatch):
    monkeypatch.delenv("SKENER_NAZIV", raising=False)
    monkeypatch.delenv("SKENER_KONTAKT", raising=False)


def test_podrazumevana_konfiguracija_nema_identitet(bez_okruzenja):
    with pytest.raises(ConfigError, match="identitet"):
        user_agent(load_config())


@pytest.mark.parametrize(
    "naziv, kontakt",
    [
        pytest.param("", "kontakt@primer.rs", id="nv-bez-naziva"),
        pytest.param("Web studio Primer", "", id="nv-bez-kontakta"),
        pytest.param("   ", "kontakt@primer.rs", id="nv-samo-razmaci"),
    ],
)
def test_nepotpun_identitet_puca(bez_okruzenja, naziv, kontakt):
    cfg = load_config()
    cfg["identitet"] = {"naziv": naziv, "kontakt": kontakt}
    with pytest.raises(ConfigError, match="identitet"):
        user_agent(cfg)


def test_user_agent_nosi_operatera_a_ne_autora(bez_okruzenja):
    cfg = load_config()
    cfg["identitet"] = {"naziv": "Web studio Primer", "kontakt": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert "Web studio Primer" in ua and "kontakt@primer.rs" in ua
    assert "miloslazic458" not in ua


def test_identitet_iz_okruzenja_ima_prednost(monkeypatch):
    """Za Docker: `SKENER_NAZIV` i `SKENER_KONTAKT` se prosleđuju iz compose.yaml."""
    monkeypatch.setenv("SKENER_NAZIV", "Iz okruženja")
    monkeypatch.setenv("SKENER_KONTAKT", "env@primer.rs")
    cfg = load_config()
    cfg["identitet"] = {"naziv": "Iz fajla", "kontakt": "fajl@primer.rs"}
    ua = user_agent(cfg)
    assert "Iz okruzenja" in ua and "env@primer.rs" in ua  # ASCII: ž → z


# Pogađanje grešaka: kupac upisuje ime kako mu je prirodno, a HTTP zaglavlje sme da
# nosi samo ASCII. Ime sa „Š" ili ćirilicom inače obori svaki zahtev.
@pytest.mark.parametrize(
    "naziv, ocekivano",
    [
        pytest.param("Web studio Šumadija", "Web studio Sumadija", id="pg-latinica-dijakritici"),
        pytest.param("Đorđe Čačić", "Djordje Cacic", id="pg-dj-i-c"),
        pytest.param("Ђорђе Јовановић", "Djordje Jovanovic", id="pg-cirilica"),
        pytest.param("Студио Љубљана", "Studio Ljubljana", id="pg-cirilica-lj"),
        pytest.param("Studio — Primer", "Studio Primer", id="pg-crta-otpada"),
        pytest.param("Studio 😀 Primer", "Studio Primer", id="pg-emodzi-otpada"),
    ],
)
def test_identitet_se_presipa_u_ascii(bez_okruzenja, naziv, ocekivano):
    cfg = load_config()
    cfg["identitet"] = {"naziv": naziv, "kontakt": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert ua.isascii(), ua
    assert ocekivano in ua


def test_identitet_ne_moze_da_ubaci_novo_zaglavlje(bez_okruzenja):
    """Novi red u imenu bi u HTTP zahtevu započeo novo zaglavlje."""
    cfg = load_config()
    cfg["identitet"] = {"naziv": "Studio\r\nX-Napad: 1", "kontakt": "kontakt@primer.rs"}
    ua = user_agent(cfg)
    assert "\r" not in ua and "\n" not in ua


def test_identitet_od_samih_ne_ascii_znakova_puca(bez_okruzenja):
    cfg = load_config()
    cfg["identitet"] = {"naziv": "😀😀", "kontakt": "kontakt@primer.rs"}
    with pytest.raises(ConfigError, match="identitet"):
        user_agent(cfg)


# --------------------------------------------------------------------------- #
# Granica 0 u konfiguraciji: semafor sa nula mesta ne pušta nikog — prolaz bi
# stajao zauvek, bez ijedne poruke.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kljuc",
    ["http.concurrency", "http.domain_concurrency", "browser.concurrency", "http.max_requests_per_domain"],
)
@pytest.mark.parametrize(
    "vrednost, ispravna",
    [
        pytest.param(-1, False, id="nv-negativna"),
        pytest.param(0, False, id="gv-0"),
        pytest.param(1, True, id="gv-1"),
    ],
)
def test_paralelizam_i_budzet_moraju_biti_pozitivni(tmp_path, kljuc, vrednost, ispravna):
    sekcija, polje = kljuc.split(".")
    override = tmp_path / "moj.toml"
    override.write_text(f"[{sekcija}]\n{polje} = {vrednost}\n", encoding="utf-8")
    if ispravna:
        assert get(load_config(override), kljuc) == vrednost
    else:
        with pytest.raises(ConfigError, match=kljuc):
            load_config(override)


def test_neispravan_toml_puca_i_imenuje_fajl(tmp_path):
    override = tmp_path / "pokvaren.toml"
    override.write_text("[http\nconcurrency = 8\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="pokvaren.toml"):
        load_config(override)


def test_nepostojeci_config_fajl_puca(tmp_path):
    with pytest.raises(ConfigError, match="ne postoji"):
        load_config(tmp_path / "nema.toml")


@pytest.mark.parametrize(
    "vrednost, ispravna",
    [
        pytest.param(0, False, id="gv-0"),
        pytest.param(-5, False, id="nv-negativna"),
        pytest.param(0.5, True, id="gv-malo-iznad-0"),
        pytest.param(40, True, id="ke-podrazumevana"),
    ],
)
def test_vremenski_budzet_mora_biti_pozitivan(tmp_path, vrednost, ispravna):
    override = tmp_path / "moj.toml"
    override.write_text(f"[http]\nmax_seconds_per_domain = {vrednost}\n", encoding="utf-8")
    if ispravna:
        assert get(load_config(override), "http.max_seconds_per_domain") == vrednost
    else:
        with pytest.raises(ConfigError, match="max_seconds_per_domain"):
            load_config(override)


def test_konfiguracija_iz_radnog_direktorijuma_ima_prednost(tmp_path, monkeypatch):
    import shutil

    from skener.config import default_config_path

    kopija = tmp_path / "skener.toml"
    shutil.copy(default_config_path(), kopija)
    monkeypatch.chdir(tmp_path)
    assert default_config_path() == kopija


def test_bez_podrazumevane_konfiguracije_puca_i_kaze_sta_da_se_uradi(monkeypatch):
    monkeypatch.setattr("skener.config.CONFIG_NAME", "nepostojeci.toml")
    with pytest.raises(ConfigError, match="--config"):
        load_config()


@pytest.mark.parametrize("sekcija", ["severity_points", "industry_multipliers"])
def test_nedostaje_cela_sekcija(sekcija):
    cfg = load_config()
    del cfg[sekcija]
    with pytest.raises(ConfigError, match=sekcija):
        _validate(cfg)


# --------------------------------------------------------------------------- #
# Otisak konfiguracije: `diff` po njemu zna da li je razlika od sajta ili od pragova
# --------------------------------------------------------------------------- #
def test_otisak_ne_zavisi_od_identiteta_i_paralelizma():
    prva, druga = load_config(), load_config()
    druga["identitet"] = {"naziv": "Drugi studio", "kontakt": "drugi@primer.rs"}
    druga["http"]["concurrency"] = druga["http"]["domain_concurrency"] = 2
    druga["browser"]["concurrency"] = 1
    druga["browser"]["executable_path"] = "/usr/bin/chromium"
    assert digest(prva) == digest(druga)
    assert len(digest(prva)) == 64


@pytest.mark.parametrize(
    "kljuc, vrednost",
    [
        pytest.param(("thresholds", "perf", "html_size_kb"), 501, id="prag"),
        pytest.param(("severity_points", "critical"), 41, id="bodovi"),
        pytest.param(("industry_multipliers", "hotel", "social"), 1.4, id="mnozilac"),
        pytest.param(("escalation", "max_level2"), 59, id="limit-nivoa-2"),
    ],
)
def test_otisak_se_menja_kad_se_promeni_prag(kljuc, vrednost):
    cfg = load_config()
    pre = digest(cfg)
    *put, poslednji = kljuc
    sekcija = cfg
    for deo in put:
        sekcija = sekcija[deo]
    sekcija[poslednji] = vrednost
    assert digest(cfg) != pre
