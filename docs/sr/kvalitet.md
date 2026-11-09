# Skener kroz ISO/IEC 25010

Za svaku od osam karakteristika modela kvaliteta proizvoda (verzija 25010:2011) ovde piše šta alat
radi, **čime se to dokazuje** (test ili modul) i gde je rupa. Tvrdnja bez dokaza ovde ne stoji: ako
kolona „Dokaz" ne može da se popuni, tvrdnja ide u „Rupe".

## 1. Funkcionalna podobnost — radi li ono što treba?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| kompletnost | 30 provera, sve iz jednog registra | `checks/registry.py`; CI poredi registar sa tabelom u README-u |
| ispravnost | svaki pozitivan test kvari tačno jednu stvar na čistom sajtu | `tests/factories.py`, `test_checks_level1.py`, `test_checks_level2.py` |
| ispravnost | broj u rečenici za klijenta mora postojati u dokazu; tvrdnja mora biti proverljiva; broj i imenica se slažu | `test_messages.py` |
| ispravnost | ono što se ne zna je `unknown`, ne nalaz: sajt iza zaštite od botova, prekinuto TLS rukovanje | `test_blocked_site_has_no_finding`, `test_entry_request_state_transitions` |
| ispravnost | težina stranice je ono što je preneto preko mreže, ne raspakovano telo | `test_weight_counts_transferred_bytes_not_decompressed` |
| ispravnost | sajt koji se ne otvara ni u drugom pokušaju ide u „Ne rade", ne u rangiranje | `test_unreachable_is_not_in_the_ranking` |
| prikladnost | delatnost menja težinu nalaza, ne ozbiljnost | `score.weigh`, `test_score.py` |

**Rupe.** Pragovi težine, broja zahteva i vremena su kalibrisani nad 58 sajtova liste A (Z-50) i
provereni na novoj listi B: u ručnoj proveri prvih 10 nijedan od 89 nalaza nije bio netačan
([IT-SKENER-003](izvestaj-testiranja-3.md)). Za druge delatnosti i tržišta raspodela može biti
drugačija, pa kalibraciju treba ponavljati nad listama operatera ([`kalibracija.md`](kalibracija.md)).
Naslov, opis i canonical se čitaju iz sirovog HTML-a; koliko sajtova ih postavlja JavaScript-om tek
se meri.
Sa adrese van Srbije deo sajtova izgleda kao da ne radi, jer ih hosting odbija, pa lista „Ne rade"
važi samo za prolaz sa adrese u Srbiji (kalibracija, 28.09.).

## 2. Performansna efikasnost — radi li dovoljno brzo i uz razumne resurse?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| vremensko ponašanje | domeni idu paralelno; budžet vremena teče tek kad domen dobije red | `test_domains_run_in_parallel_not_one_after_another`, `test_time_budget_starts_only_when_the_domain_gets_its_turn` |
| iskorišćenje resursa | nivo 2 na 3 konteksta (svaki su stotine MB), gornji limit od 60 domena | `sitetriage.toml` (`[browser]`, `[escalation]`), `score.select_for_level2` |
| kapacitet | tvrd budžet: 19 zahteva i 40 s po domenu; tvrd limit od 60 s za nivo 2 | `test_budget_is_respected_on_every_domain`, `test_time_budget_boundary`, `test_hard_per_domain_limit_aborts_level_2`; vrednosti u `sitetriage.toml` (`[http]`, `[browser]`) |
| vremensko ponašanje | vreme učitavanja se meri pod fiksnim mrežnim profilom i bez tuđeg saobraćaja na vezi; na 10 pravih sajtova u prolazu je 19 od 20 odnosa 0,8–1,25× vremena kad se sajt meri sam | `test_profile_slows_down_loading`, `test_loads_of_different_sites_do_not_overlap`, [`kalibracija.md`](kalibracija.md) (Z-31) |

**Rupe.** U1 („200 domena ≤ 15 min") zavisi od veze. Na 107 Mb/s (prolaz H nad 100 domena) nivo 1
traje 168 s, a nivo 2 500 s, pa je procena za 200 domena 13,9 min, jer nivo 1 raste linearno, a
nivo 2 je ograničen na 60 domena. Na 17 Mb/s je procena 19,1 min. Nivo 2 učitava jedan po jedan
pod profilom od 4,8 Mb/s, pa taj deo ne ubrzava ni najbrža veza. Od BUG-020 ostali sajtovi dobijaju
lagani nivo 2, pa je procena nad listom B sa 3 konteksta oko 23 min. Granica od 15 min zato važi za
preporučenu mašinu (16 GB RAM, veza ≥ 50 Mb/s), na kojoj još nije izmerena; meri se na prvom
prolazu sa VPS-a. VPS van Srbije nosi rizik iz funkcionalne podobnosti: deo hostinga odbija veze
iz datacentra.

## 3. Kompatibilnost — radi li zajedno sa drugim sistemima?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| interoperabilnost | CSV po RFC 4180, BOM samo na zahtev (Excel) | `report/csv_out.py`, `test_bom_is_written_only_when_asked_for` |
| interoperabilnost | HTML izveštaj je jedan fajl bez CDN-a | `test_html_is_self_contained` |
| interoperabilnost | JSON izveštaj sa verzijom šeme; izlaz se validira po šemi | `test_json_report_matches_the_schema` |
| koegzistencija | poštuje `robots.txt` i `Crawl-delay`; jasan User-Agent sa kontaktom | `test_robots_disallow_is_obeyed`, `test_crawl_delay_from_robots_is_obeyed`, `test_user_agent_carries_the_operator_not_the_author` |

**Rupe.** JSON izveštaj sa verzijom šeme postoji (`report.json`, šema `schema/report-3.json`), ali CRM
integracija nije napravljena. Nju pravi onaj ko ga čita.

## 4. Upotrebljivost — može li korisnik da ga koristi?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| prepoznatljivost | izveštaj daje rangiranu listu i gotove rečenice za mejl | `docs/sample-report-sr.html`, `docs/sample-report.html` |
| učljivost | `sitetriage explain <check_id>` objašnjava prag i poruku | `test_explain_prints_the_threshold_and_the_sentence` |
| zaštita od greške | CSV bez kolone `domain` puca razumljivo; nepoznata provera predlaže slične | `test_csv_without_a_domain_column_fails_clearly`, `test_explain_of_an_unknown_check_suggests_similar_ones` |
| zaštita od greške | lista iz Excel-a radi i sa `;` i u windows-1250; duplikati se skeniraju jednom; nula ili negativan broj u konfiguraciji se odbija | `test_csv_from_excel_with_semicolons`, `test_csv_in_windows_1250`, `test_csv_duplicates_are_scanned_once`, `test_concurrency_and_budget_must_be_positive` |
| pristupačnost | ozbiljnost ima oznaku i znak, ne samo boju | `test_severity_has_a_label_and_a_glyph_not_only_a_colour` |

**Rupe.** Napredak se vidi kao brojač u logu („level 1: 43/200 done"), a traka napretka postoji
tek kad je napravi pozivalac iz događaja `on_event` (web aplikacija). Log je JSON na stderr, što je
za nekog ko nije programer i dalje teško za čitanje.

## 5. Pouzdanost — radi li stabilno tokom vremena?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| otpornost na greške | izuzetak nikad ne napušta domen; svaka provera u sopstvenom `try` | `test_u2_as_many_out_as_in`, `registry.run` |
| otpornost na greške | četiri stanja rezultata: `ok`, `finding`, `unknown` i `not_applicable`, poslednja dva sa obaveznim razlogom | `test_broken_domains_are_failed_not_an_exception`, `test_not_applicable_without_reason_is_a_bug` |
| oporavljivost | snapshot ide na disk čim je domen gotov; `recheck` ponavlja bodovanje bez mreže | `test_snapshot_is_written_to_disk_as_soon_as_the_domain_is_done`, `test_recheck_gives_the_same_result_without_a_single_request` |
| zrelost | determinističko uzorkovanje i sonde, pa isti ulaz daje isti izlaz | `test_sampling_is_deterministic_and_grouped`, `test_probes_are_deterministic` |

**Rupe.** Prekinut prolaz ne može da se nastavi: snapshoti postoje, ali `scan` ih ne preskače.
Zrelost je izmerena samo na listi A: prolazi D do H i prolaz sa GitHub-a završeni su bez pada, a
na brzoj vezi i bez ijednog WARNING-a ili ERROR-a u logu ([`kalibracija.md`](kalibracija.md)).

## 6. Bezbednost — jesu li podaci zaštićeni?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| integritet | domen iz CSV-a ne može da izađe iz izlaznog foldera | `test_directory_name_does_not_leave_the_output_directory` |
| poverljivost | privatne adrese se ne otvaraju, ni posle DNS-a ni posle preusmerenja (SSRF) | `test_ssrf.py`, `test_addresses.py`, [ADR-006](../adr/ADR-006-ssrf.md) |
| integritet | tuđ sadržaj je granica poverenja: prevelik sitemap se odbija, HTML sa sajta se escape-uje u izveštaju | `test_oversized_sitemap_is_refused`, `test_html_escapes_html_from_site_content` |
| odgovornost | User-Agent nosi ime i kontakt operatera, ne autora; bez njih nema nijednog zahteva | `test_scan_without_identity_refuses_before_a_single_request` |
| integritet | ime operatera ne može da ubaci novo HTTP zaglavlje | `test_identity_cannot_inject_a_new_header` |
| poverljivost | izveštaji i snapshoti su van git-a | `.gitignore` (`work/`, `izvestaj/`, `snapshots/`, `out/`) |

**Rupe.** Alat namerno ne skenira ranjivosti, pa „bezbednost" ovde znači bezbednost *alata*, ne
sajta. Izuzetak je TLS nalaz. `tests/fixtures/` posle `record` sadrže javni HTML tuđih sajtova u git-u.

## 7. Održivost — može li se lako menjati?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| modularnost | provere ne uvoze mrežu; sloj mreže i sloj zaključaka su odvojeni | README „How it works", `test_architecture.py`, `checks/registry.py` |
| ponovna upotrebljivost | nova provera = jedna funkcija sa dekoratorom | `@check(...)` u `checks/*.py` |
| analizabilnost | `--debug-domain`, sirovi snapshoti na disku | `cli.setup_logging` |
| izmenljivost | svi pragovi u `sitetriage.toml`; `git diff` nad njim je istorija kalibracije | `test_config.py` |
| testabilnost | preko 1000 testova bez mreže, lokalni server umesto pravih sajtova; pokrivenost linija i grana 98 %; mutacioni skor v2 944 od 944 neekvivalentnih mutanata (100 %), bez tela provera, jer mutmut 3.2.3 funkcije sa dekoratorom ne mutira | `tests/`, CI (`--cov-fail-under=95`), `[tool.mutmut]`, `scripts/mutation.py` |

**Rupe.** `fetch/http.py` ima 979 linija i nosi četiri odgovornosti (klijent, budžet, sklapanje
snapshota, orkestracija). Sva četiri baga iz revizije v1 su bila tu. Kandidat za podelu posle v2.
mutmut 3 ne vidi kod koji radi pri importu (dekorator `check(...)`) ni testove koji računaju nalaze
pri importu modula, pa se takvi preživeli proveravaju ručno.

## 8. Prenosivost — može li se preneti u drugo okruženje?

| Potkarakteristika | Kako | Dokaz |
|---|---|---|
| instalabilnost | `pip install -e .`; nivo 2 opcion (`.[browser]`) | `pyproject.toml` |
| instalabilnost | Docker slika zaključana digest-om, sa Chromium-om za tačnu verziju Playwright-a; radi bez root-a | `Dockerfile`, `compose.yaml`, CI posao `docker` |
| prilagodljivost | sistemski Chromium preko `SITETRIAGE_CHROMIUM` / `browser.executable_path` | `browser._launch_options` |
| prilagodljivost | nivo 2 meri pod istim simuliranim mrežnim profilom na svakoj mašini; kad je stvarna veza sporija od dvostrukog profila, vreme je `unknown`, a ne precenjeno | `test_profile_is_in_the_snapshot_and_the_json`, `test_load_time_on_link_slower_than_profile_is_unknown`, [ADR-010](../adr/ADR-010-mrezni-profil.md) |
| prilagodljivost | browser testovi se preskaču uz razlog kad Chromium ne može da se pokrene | `chromium_starts` u `tests/conftest.py` |
| zamenljivost | Playwright je zakucan u `dev`, jer paket traži tačno svoju reviziju Chromium-a | `pyproject.toml` |

**Rupe.** Van Docker-a testirano samo na Linuxu (Python 3.11, 3.12 i 3.13 u CI-ju, 3.12 u slici). Windows bez Docker-a
(putanje, `asyncio` event loop) nije proveren. Procesor se ne simulira, pa vreme učitavanja i dalje
malo zavisi od mašine. Mašina koja skenira mora da ima adresu u Srbiji (§1) i brzu vezu:
na 17 Mb/s je 20,5 % domena potrošilo budžet, a na 107 Mb/s 7,8 %. Između nema merenja.

---

## Mapiranje na standarde

| Grupa | Standard | Gde se vidi u projektu |
|---|---|---|
| proizvod | ISO/IEC 25010 | ovaj dokument |
| proizvod | ISO/IEC 25040 (evaluacija) | `docs/real-site-verification.md`: merljivi kriterijumi pre v2 |
| proces | ISO/IEC/IEEE 29119 (testiranje) | [`plan-testiranja.md`](plan-testiranja.md), izveštaji o testiranju, prijave defekata BUG-001 do BUG-026; nivoi: jedinični, integracioni (lokalni server, pravi Chromium), sistemski (100 pravih domena) |
| proces | ISO/IEC/IEEE 12207 (životni ciklus) | faze 0–7 u istoriji commit-a; CI na push u `main` i na svaki PR |
| dokumentacija | IEEE 1016 (opis dizajna) | README „How it works": moduli, odgovornosti, pristup mreži i disku |
| dokumentacija | ISO/IEC/IEEE 26511/26515 (korisnička) | README „Quick start", „Input and output" i „Other commands", `sitetriage explain` |
