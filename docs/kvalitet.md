# Skener kroz ISO/IEC 25010

Za svaku od osam karakteristika modela kvaliteta proizvoda (verzija 25010:2011) ovde piše šta alat
radi, **čime se to dokazuje** (test ili modul) i gde je rupa. Tvrdnja bez dokaza ovde ne stoji: ako
kolona „Dokaz" ne može da se popuni, tvrdnja ide u „Rupe".

## 1. Funkcionalna podobnost — radi li ono što treba?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| kompletnost | 28 provera iz specifikacije, sve iz jednog registra | `checks/registry.py`; CI poredi registar sa tabelom u README-u |
| ispravnost | svaki pozitivan test kvari tačno jednu stvar na čistom sajtu | `tests/factories.py`, `test_checks_level1.py`, `test_checks_level2.py` |
| ispravnost | broj u rečenici za klijenta mora postojati u dokazu; tvrdnja mora biti proverljiva; broj i imenica se slažu | `test_poruke.py` |
| ispravnost | ono što se ne zna je `unknown`, ne nalaz: sajt iza zaštite od botova, prekinuto TLS rukovanje | `test_blokiran_sajt_nema_nijedan_nalaz`, `test_prelazi_stanja_ulaznog_zahteva` |
| ispravnost | težina stranice je ono što je preneto preko mreže, ne raspakovano telo | `test_tezina_broji_prenete_bajtove_a_ne_raspakovane` |
| prikladnost | delatnost menja težinu nalaza, ne ozbiljnost | `score.weigh`, `test_score.py` |

**Rupe.** Pragovi težine su kalibrisani nad 60 sajtova sa jedne liste leadova. Za druge delatnosti
i tržišta raspodela može biti drugačija, pa kalibraciju treba ponavljati nad listama kupaca
([`kalibracija.md`](kalibracija.md)).

## 2. Performansna efikasnost — radi li dovoljno brzo i uz razumne resurse?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| vremensko ponašanje | domeni idu paralelno; budžet vremena teče tek kad domen dobije red | `test_domeni_idu_paralelno_a_ne_jedan_za_drugim`, `test_budzet_vremena_krece_tek_kad_domen_dobije_red` |
| iskorišćenje resursa | nivo 2 na 3 konteksta (svaki su stotine MB), gornji limit od 60 domena | `skener.toml [browser]`, `score.select_for_level2` |
| kapacitet | tvrd budžet: 19 zahteva i 40 s po domenu; tvrd limit od 60 s za nivo 2 | `test_budzet_se_postuje_na_svakom_domenu`, `test_tvrdi_limit_po_domenu_prekida_nivo_2` |
| vremensko ponašanje | vreme učitavanja se meri bez tuđeg saobraćaja na vezi; na 10 pravih sajtova u prolazu je 0,72–1,24× vremena kad se sajt meri sam | `test_ucitavanja_razlicitih_sajtova_se_ne_preklapaju`, [`izvestaj-testiranja-2.md`](izvestaj-testiranja-2.md) |

**Rupe.** U1 („200 domena ≤ 15 min") je izmeren na 100 domena: 9,3 min, od toga 3,6 min nivo 1 i
5,6 min nivo 2 ([`izvestaj-testiranja-2.md`](izvestaj-testiranja-2.md)). Za 200 domena je procena
oko 13 min, jer nivo 1 raste linearno, a nivo 2 je ograničen na 60 domena. Rezerva je mala: nivo 2
sada učitava jedan po jedan, pa svaki spor sajt produžava ceo prolaz.

## 3. Kompatibilnost — radi li zajedno sa drugim sistemima?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| interoperabilnost | CSV po RFC 4180, BOM samo na zahtev (Excel) | `report/csv_out.py`, `test_bom_se_pise_samo_kad_se_trazi` |
| interoperabilnost | HTML izveštaj je jedan fajl bez CDN-a | `test_html_je_samostalan` |
| interoperabilnost | JSON izveštaj sa verzijom šeme; izlaz se validira po šemi | `test_json_izvestaj_prolazi_semu` |
| koegzistencija | poštuje `robots.txt` i `Crawl-delay`; jasan User-Agent sa kontaktom | `test_robots_disallow_se_postuje` |

**Rupe.** JSON izveštaj sa verzijom šeme postoji (`report.json`, šema `report-2.json`), ali CRM
integracija nije napravljena. Nju pravi onaj ko ga čita.

## 4. Upotrebljivost — može li korisnik da ga koristi?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| prepoznatljivost | izveštaj daje rangiranu listu i gotove rečenice za mejl | `docs/primer-izvestaja.html` |
| učljivost | `skener explain <check_id>` objašnjava prag i poruku | `test_explain_ispisuje_prag_i_recenicu` |
| zaštita od greške | CSV bez kolone `domain` puca razumljivo; nepoznata provera predlaže slične | `test_csv_bez_kolone_domain_puca_razumljivo` |
| zaštita od greške | lista iz Excel-a radi i sa `;` i u windows-1250; duplikati se skeniraju jednom; nula ili negativan broj u konfiguraciji se odbija | `test_csv_iz_excela_sa_tackom_zarezom`, `test_paralelizam_i_budzet_moraju_biti_pozitivni` |
| pristupačnost | ozbiljnost ima oznaku i znak, ne samo boju | `test_ozbiljnost_ima_oznaku_i_znak_a_ne_samo_boju` |

**Rupe.** Napredak se vidi kao brojač u logu („nivo 1: 43/200 gotovo"), a traka napretka postoji
tek kad je napravi pozivalac iz događaja `on_event` (web aplikacija). Log je JSON na stderr, što je
za nekog ko nije programer i dalje teško za čitanje.

## 5. Pouzdanost — radi li stabilno tokom vremena?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| otpornost na greške | izuzetak nikad ne napušta domen; svaka provera u sopstvenom `try` | `test_u2_koliko_udje_toliko_izadje`, `registry.run` |
| otpornost na greške | tri stanja rezultata: `ok`, `finding`, `unknown` sa obaveznim razlogom | `test_pokvareni_domeni_su_failed_a_ne_izuzetak` |
| oporavljivost | snapshot ide na disk čim je domen gotov; `recheck` ponavlja bodovanje bez mreže | `test_snapshot_se_pise_na_disk_cim_je_domen_gotov`, `test_recheck_daje_isti_rezultat_bez_ijednog_zahteva` |
| zrelost | determinističko uzorkovanje i sonde, pa isti ulaz daje isti izlaz | `test_uzorkovanje_je_deterministicko_i_grupisano`, `test_sonde_su_deterministicke` |

**Rupe.** Prekinut prolaz ne može da se nastavi: snapshoti postoje, ali `scan` ih ne preskače.
Zrelost je nepoznata dok alat ne prođe bar jedan pravi prolaz.

## 6. Bezbednost — jesu li podaci zaštićeni?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| integritet | domen iz CSV-a ne može da izađe iz izlaznog foldera | `test_ime_direktorijuma_ne_izlazi_iz_izlaznog_foldera` |
| poverljivost | privatne adrese se ne otvaraju, ni posle DNS-a ni posle preusmerenja (SSRF) | `test_ssrf.py`, `test_addresses.py`, [ADR-006](adr/ADR-006-ssrf.md) |
| integritet | tuđ sadržaj je granica poverenja: prevelik sitemap se odbija, HTML sa sajta se escape-uje u izveštaju | `test_prevelik_sitemap_se_odbija`, `test_html_bezi_od_html_a_iz_sadrzaja_sajta` |
| odgovornost | User-Agent nosi ime i kontakt operatera, ne autora; bez njih nema nijednog zahteva | `test_scan_bez_identiteta_odbija_pre_ijednog_zahteva` |
| integritet | ime operatera ne može da ubaci novo HTTP zaglavlje | `test_identitet_ne_moze_da_ubaci_novo_zaglavlje` |
| poverljivost | izveštaji i snapshoti su van git-a | `.gitignore` (`izvestaj/`, `snapshots/`, `out/`) |

**Rupe.** Alat namerno ne skenira ranjivosti, pa „bezbednost" ovde znači bezbednost *alata*, ne
sajta. Izuzetak je TLS nalaz. `tests/fixtures/` posle `record` sadrže javni HTML tuđih sajtova u git-u.

## 7. Održivost — može li se lako menjati?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| modularnost | provere ne uvoze mrežu; sloj mreže i sloj zaključaka su odvojeni | README „Kako je podeljen", `checks/registry.py` |
| ponovna upotrebljivost | nova provera = jedna funkcija sa dekoratorom | `@check(...)` u `checks/*.py` |
| analizabilnost | `--debug-domain`, sirovi snapshoti na disku | `cli.setup_logging` |
| izmenljivost | svi pragovi u `skener.toml`; `git diff` nad njim je istorija kalibracije | `test_config.py` |
| testabilnost | preko 600 testova bez mreže, lokalni server umesto pravih sajtova; pokrivenost linija i grana 97 %, mutacioni skor 100 % neekvivalentnih | `tests/`, CI (`--cov-fail-under=95`), `[tool.mutmut]` |

**Rupe.** `fetch/http.py` ima 550 linija i nosi četiri odgovornosti (klijent, budžet, sklapanje
snapshota, orkestracija). Sva četiri baga iz revizije su bila tu. Kandidat za podelu u v2.

## 8. Prenosivost — može li se preneti u drugo okruženje?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| instalabilnost | `pip install -e .`; nivo 2 opcion (`.[browser]`) | `pyproject.toml` |
| instalabilnost | Docker slika zaključana digest-om, sa Chromium-om za tačnu verziju Playwright-a; radi bez root-a | `Dockerfile`, `compose.yaml`, CI posao `docker` |
| prilagodljivost | sistemski Chromium preko `SKENER_CHROMIUM` / `browser.executable_path` | `browser._launch_options` |
| prilagodljivost | browser testovi se preskaču uz razlog kad Chromium ne može da se pokrene | `chromium_se_pokrece` u `test_fetch_browser.py` |
| zamenljivost | Playwright je zakucan u `dev`, jer paket traži tačno svoju reviziju Chromium-a | `pyproject.toml` |

**Rupe.** Van Docker-a testirano samo na Linuxu (Python 3.11 u CI-ju, 3.12 u slici). Windows bez Docker-a
(putanje, `asyncio` event loop) nije proveren.

---

## Mapiranje na standarde

| Grupa | Standard | Gde se vidi u projektu |
|---|---|---|
| proizvod | ISO/IEC 25010 | ovaj dokument |
| proizvod | ISO/IEC 25040 (evaluacija) | `docs/provera-na-pravim-sajtovima.md`: merljivi kriterijumi pre v2 |
| proces | ISO/IEC/IEEE 29119 (testiranje) | [`plan-testiranja.md`](plan-testiranja.md), izveštaji o testiranju, prijave defekata BUG-001 do BUG-015; nivoi: jedinični, integracioni (lokalni server, pravi Chromium), sistemski (100 pravih domena) |
| proces | ISO/IEC/IEEE 12207 (životni ciklus) | faze 0–7 u istoriji commit-a; CI na push u `main` i na svaki PR |
| dokumentacija | IEEE 1016 (opis dizajna) | README „Kako je podeljen": moduli, odgovornosti, pristup mreži i disku |
| dokumentacija | ISO/IEC/IEEE 26511/26515 (korisnička) | README „Upotreba", `skener explain` |
