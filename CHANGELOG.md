# Izmene

Ovde su izmene koje primeti onaj ko koristi alat ili čita njegov izlaz. Verzije prate semver:
izmena koja lomi kompatibilnost (status domena, `check_id`, oblik nalaza, JSON) podiže prvi broj.

## 2.0.0 — u izradi

Tokom rada verzija je `2.0.0.dev0`. Postaje `2.0.0`, uz tag `v2.0.0`, kad su ispunjeni izlazni
kriterijumi v2 iz [plana testiranja](docs/plan-testiranja.md).

### Izmene koje lome kompatibilnost

Svaka takva izmena upisuje se ovde u istom commit-u u kom je urađena.

- Razlog za `unknown` i razlog eskalacije više nisu rečenice nego `Reason(code, evidence)`, u
  modelu i u JSON-u (`unknowns[].reason`, `escalation_reasons[]`). Rečenicu pravi
  `skener.messages.reason(razlog, lang)`, pa su razlozi u izveštaju na engleskom sada na
  engleskom.
- `Finding` više nema `message_client` ni `message_tech`. Rečenicu pravi
  `skener.messages.render(finding, lang)` pri prikazu, a nalaz dobija `variant`
  ([ADR-009](docs/adr/ADR-009-katalog-poruka.md)). Kolona `message_client` u `findings.csv` ostaje.
- Dokaz nalaza je samo podatak. Nestali su složeni oblici `uz_video`, `preuzimanja`,
  `greske_tekst`, `kopije`, `stranice`, `naslovi` i `od_slika`. `uzorak` je kod (`sitemap`,
  `links`, `none`), nedostajuće kodiranje je `null` umesto „nema", a `lanac` preusmerenja je
  lista URL-ova umesto teksta sa strelicama.
- Privatne i posebne adrese se više ne otvaraju (SSRF, [ADR-006](docs/adr/ADR-006-ssrf.md)).
  Domen sa IP adresom, portom ili korisničkim imenom je `failed` bez ijednog zahteva, osim kad je
  `host:port` naveden u `[net] allowed_private`. Nivo 1 više ne čita `HTTP(S)_PROXY`.
- `CheckSpec` više nema šablone `message_template` i `tech_template`, a `check()` ne prima
  `message` ni `tech`. Modul `skener.checks.srpski` je prešao u `skener.messages.sr`.
- `infra.dns.unresolved` je obrisan. Sajt koji se ne otvori ni u drugom pokušaju dobija nalaz
  `infra.unreachable` i status `unreachable`, i ide u listu „Ne rade" umesto u rangiranje.
  `rank()` rangira samo `scanned` i `partial`, a ostali domeni imaju `rank` 0. JSON ima liste
  `unreachable` i `not_scanned`, a izveštaj domena polje `reason` (zašto je `failed`).
- Provera ima i četvrto stanje, `not_applicable`, sa obaveznim razlogom. Izveštaj domena ima listu
  `not_applicable` u istom obliku kao `unknowns`, ali ona ne čini domen `partial`.
- Vrsta greške `dns` u snapshotu je podeljena na `dns_nxdomain`, `dns_nodata` (ime postoji, ali
  nema adresu), `dns_temporary` i `dns` (ostale DNS greške). TCP veza koja nije uspostavljena je `no_connection`.
- `CheckSpec` više nema `optional`, `check()` ga ne prima, a `Context` nema `host_canonicalization`.
  Nijedna provera ih nije koristila; kanonizacija hosta je sada obična provera.
- `thresholds.perf.mobile_speed_mbps` je obrisan. Brzina je sada `network_profile.download_mbps`, i
  ista vrednost ide u merenje i u rečenice. Stari ključ u sopstvenom TOML-u se tiho ignoriše.
- `perf.load.time` traži snimak sa mrežnim profilom. Snimak nivoa 2 napravljen pre njega meren je na
  stvarnoj vezi, pa je vreme `unknown` (`requires.network_profile`). Isto važi i za snimak bez
  izmerene stvarne veze (`requires.link`, Z-33). JSON `environment` ima obavezna polja
  `network_profile` i `link_mbps` (`null` kad nivo 2 nije radio).

### Dodato

- Mrežni profil nivoa 2. Svaka stranica se meri na simuliranoj vezi iz `[network_profile]`
  (4,8 Mb/s dolazno, 1,5 Mb/s odlazno, 150 ms kašnjenja), pa isti sajt daje isto vreme na svakoj
  mašini. Profil je u snimku nivoa 2 (`network_profile`) i u `environment` JSON izveštaja, a
  rečenica za `perf.load.time` ga navodi. Chromium se pokreće bez izolacije sajtova, da profil važi
  i za iframe sa drugog sajta ([ADR-010](docs/adr/ADR-010-mrezni-profil.md)).
- Merenje stvarne veze pre nivoa 2. Alat jednom po prolazu preuzima probni fajl
  (`network_profile.probe_url`, najviše `probe_max_s` sekundi), a izmerena brzina ide u snimak
  (`link_mbps`) i u `environment` JSON izveštaja. Kad je veza sporija od `min_link_ratio` × profil,
  `perf.load.time` je `unknown` (`link_slow`), jer profil može samo da uspori, a vreme bi bilo
  precenjeno. Snimak bez izmerene veze daje `unknown` (`requires.link`), uz jedno upozorenje u logu (Z-33).
- Snimak nivoa 2 beleži trajanje nivoa 2 za domen (`elapsed_ms`), bez čekanja u redu za
  učitavanje, isto vreme koje ograničava `browser.max_seconds_per_domain`. Skripta
  `scripts/raspodela.py` iz snimaka ispisuje raspodelu težine, broja zahteva i vremena do `load`,
  trajanja nivoa 2 i canonical nalaze, za kalibraciju pragova (Z-50).
- Prekidač `browser.serial_load` (podrazumevano `true`). Sa `false` se sajtovi na nivou 2 učitavaju
  uporedo, a ne jedan po jedan. Pod mrežnim profilom svaki kontekst ima svoju simuliranu vezu, pa se
  eksperimentom proverava da li je serijsko učitavanje iz BUG-006 i dalje potrebno (Z-31).
- Kanonizacija hosta. Posle `robots.txt` alat dohvata preostale tri adrese konačnog porekla
  (`http`/`https` × sa i bez `www`) i beleži ih u `SiteSnapshot.host_variants`. Dve nove provere:
  `infra.https.redirect.missing` (sajt radi na https-u, a `http://` istog hosta vraća 200 bez
  preusmerenja) i `infra.host.duplicate` (sajt se otvara i sa `www` i bez `www`, a nijedna adresa ne
  preusmerava na drugu; `low` kad canonical na svima upućuje na isto poreklo). Budžet po domenu je
  19 zahteva umesto 16. Ulaz sa IP adresom ili portom nema varijante.
- Uzrok `partial`-a: izveštaj domena ima `partial_causes` (`budget`, `unknown`), zbir ih broji
  posebno, a JSON i HTML daju udeo budžeta među domenima koji rade i udeo `unknown`-a po proveri
  (`budget_share`, `unknown_share`).
- JSON izveštaj `report.json` sa verzijom šeme (`skener/schema/report-2.json`), otiskom
  konfiguracije i okruženjem. `--format` ga podrazumevano piše uz HTML i CSV.
- Snapshot nivoa 2 beleži verziju Chromium-a kojim je meren.
- Izuzeti domeni: `[identitet] izuzeti` ili `--exclude FILE`, jedan domen po redu, uz sve
  poddomene. Izuzet domen ne dobija nijedan zahtev; u izveštaju je samo njihov broj (status
  `excluded` u zbiru).
- Izveštaji na srpskom i engleskom: `--lang sr|en` za `scan` i `recheck`. `skener explain`
  ispisuje rečenice na oba jezika.
- Ceo prolaz je u modulu `skener.pipeline`, pa ga web aplikacija zove isto kao komandna linija
  ([ADR-008](docs/adr/ADR-008-pipeline.md)).
- Log tokom prolaza ima brojač napretka („nivo 1: 43/200 gotovo").
- Sajt koji posle prvog pokušaja izgleda kao da ne radi ide na kraj reda nivoa 1 i dobija drugi
  pokušaj, sa novim budžetom, najranije `http.second_attempt_after_s` (60 s) posle prvog.
- HTML izveštaj ima odeljke „Ne rade", sa posebnim nacrtom mejla, i „Nije skenirano", sa
  razlogom i brojem izuzetih domena.
- Kad mapa sajta navodi manje adresa nego što uzorak traži, uzorak se dopunjava vezama sa početne.
  Snapshot beleži interne veze sa početne, a nivo 2 i veze iz renderovanog DOM-a.
- Greška i upozorenje u listi domena navode red u kom su, onako kako ga prikazuje Excel
  („red 3: domen se ponavlja u listi").
- Lagani nivo 2 bira broj konteksta po mašini: jedan na svaki slobodan GB memorije, najviše dva
  po jezgru i najviše 8. Pun nivo 2 i dalje radi sa `browser.concurrency`, jer učitava jedan po
  jedan. `browser.light_concurrency = 0` je automatski izbor, a broj ≥ 1 ga fiksira. Na listi B
  je lagani nivo 2 sa tri konteksta trajao 168 s za 40 sajtova, a na 200 domena ih je oko 140
  (Z-32).

### Promenjeno

- Pragovi težine, broja zahteva i vremena učitavanja kalibrisani su na listi A, pod mrežnim
  profilom: težina do `load` bez videa 2 / 4 / 7 MB (bilo 3 / 5 / 8), zahtevi do `load` 60 / 90
  (bilo 100 / 150), vreme do `load` 6 / 9 s (bilo 4 / 8). To su zaokruženi p50, p75 i p90; kod
  provera sa dva nivoa medium je p50, a high p75 (Z-50, [kalibracija](docs/kalibracija.md)).

### Ispravljeno

- Recenzija kataloga poruka: rečenice više ne tvrde ništa što dokaz ne pokriva. h1, alt i lang se
  mere samo na početnoj, pa to i piše („Početna strana nema glavni naslov"). Lažni 404 kaže da sajt
  „odgovara kao da stranica postoji", a ne da vraća običnu stranicu. Ponovljen naslov i opis više
  ne tvrde kako izgledaju u Google rezultatima. „lang" sa pogrešnim zapisom (`en_EN`) nije oznaka
  „bez jezika". Bez izvora su izbačeni „mnogi posetioci ne čekaju toliko" (težina i vreme) i „Viber
  grupe" (og:image); „mnogi" i „često" su na listi reči koje traže izvor. Tekst izveštaja više ne
  tvrdi da alat ne dira ono što `robots.txt` zabranjuje: početnu i dve sonde za 404 otvara uvek.
  Ispravljeni su i razlozi `requires.entry`, `requires.soft404` i `no_h1_raw`, engleski
  `requires.robots`, `requires.sitemap` i pretpostavka u izveštaju, kao i padeži („bodovi: 24",
  „od 22 slike", „301 znak").
- Nivo 2 nije gledao HTTP status početne, pa je strana greške merena kao početna. Na listi B jedan
  server je UA sa „HeadlessChrome" odbio sa 403, a alat je izmerio stranu greške od 358 B umesto
  prave od oko 2 MB. Status ≥ 400 je sada neuspelo snimanje (`http_status`), pa su provere nivoa 2
  `unknown`. Browser se predstavlja kao „Chrome/…", a identitet operatera ostaje na kraju (BUG-021).
- Nivo 2 se predstavljao samo identitetom operatera (`MlazicSiteScanner/…`), a ne kao browser.
  Servisi koje sajt učitava biraju sadržaj po User-Agent-u: reklamne mreže su pokretale dodatne
  aukcije, a Google Fonts je slao veći format fonta. Na sajtu sa reklamama alat je izmerio 2,7 MB i
  129 zahteva, a posetilac u Chrome-u dobija 1,3 MB i oko 60. Browser sada šalje svoj UA, a
  identitet operatera je dopisan na kraj, kao kod Googlebot-a. Nivo 1 šalje isti UA kao i pre
  (BUG-019).
- Sajt bez razloga za eskalaciju ili van `max_level2` nije išao u browser, pa je u izveštaju stajao
  sa „0 nalaza", a težina, zahtevi i slike nisu ni mereni. Na listi B dve strane od 4,8 i 4,9 MB
  imale su brz i čist HTML. Takvi sajtovi sada dobijaju lagani nivo 2: posle punog nivoa 2,
  bez mrežnog profila i bez reda za učitavanje. Vreme učitavanja za njih „ne primenjuje se"
  (`not_applicable`, razlog `requires.level2_full`): sajt zbog toga ne postaje `partial`, a u
  imenilac `unknown_share` za vreme ne ulazi. Snimak nosi `light`, `duration_s` nosi
  `level2_light`, a traka napretka fazu `level2_light` (BUG-020).
- `qa.console.errors` je sve greške iz konzole nazivao „JavaScript greške", a konzola beleži i
  blokiran „Mixed Content" i resurse koji vraćaju 404. Na listi B kod 3 od 6 nalaza nijedna greška
  nije bila iz skripte. Rečenica sada kaže da Chrome prijavljuje greške i šta one mogu da budu
  (BUG-018).
- `infra.host.duplicate` je u spisak adresa stavljao i http varijante, pa je rečenica uz „2 adrese"
  nabrajala četiri kad http ne preusmerava na https. Spisak su sada hostovi (`x.rs`, `www.x.rs`), kao
  i broj; http bez preusmerenja ostaje nalaz `infra.https.redirect.missing` (BUG-017).

- `seo.canonical.duplicate` je stranicu čiji canonical upućuje na njenu `http` ili `www` verziju
  brojao kao stranicu sa tuđim canonical-om, pa je rečenica vlasniku kao „drugu adresu" pokazivala
  njegovu sopstvenu početnu. Takav canonical se više ne broji (Z-50).

- Privremena greška DNS-a (EAI_AGAIN) se ponavlja jednom, na nivou 1 i u proveri adresa na nivou 2.
  Preko mobilnog hotspota je bila na svakom četvrtom domenu, pa su sajtovi koji rade ispadali kao
  `failed`, a na nivou 2 jedna greška je blokirala sve zahteve ka tom hostu. Varijanta hosta sa
  privremenom greškom DNS-a je `unknown`, jer se ne zna da li ta adresa služi sajt.
- Nivo 1 obrađuje 16 domena odjednom umesto 8. Uglavnom čeka pauze ka istom sajtu, pa je prolaz
  nad 200 domena bio procenjen na oko 20 minuta. Pristojnost prema svakom sajtu je ista: jedan
  zahtev odjednom i ista pauza (Z-32).

- Ključ pristojnosti bio je tačan host, pa bi `www.x.rs` i `x.rs` mogli da dobiju dva zahteva
  istovremeno. Sada je ključ host bez vodećeg `www.`: oba dele red i pauzu.

- Varijanta hosta koja preusmerava na početnu preuzimala je početnu još jednom. Na sporom hostingu
  to je trošilo vremenski budžet domena pre uzorka stranica, pa je na listi A 21 domen ostao bez
  budžeta. Varijanta sada staje pred početnom i od nje uzima status i canonical.

- Jezičke provere (`i18n.lang.missing`, `invalid`, `mismatch`) gledale su samo sirovi HTML, pa je
  sajt čiji tekst crta JavaScript imao `unknown`, a `lang` koji postavi JavaScript bio je prijavljen
  kao nepostojeći. Kad je nivo 2 radio, provere sada gledaju stranicu posle JavaScript-a, onakvu
  kakvu čita čitač ekrana, a dokaz kaže izvor (`sirovi_html` ili `nivo2`). Snimak nivoa 2 beleži
  `lang` i vidljiv tekst posle JavaScript-a.

- Kad SSRF zaštita na nivou 2 odbije zahtev, Chromium javlja samo `ERR_BLOCKED_BY_CLIENT`, pa se
  neuspeo DNS upit nije razlikovao od privatne adrese. Sada log (INFO, jednom po hostu) kaže
  razlog: „DNS nije razrešio ime" ili „adresa nije javna: …".

- Težina i broj zahteva brojali su i ono što stigne posle događaja `load` (analitika, chat, lenje
  slike), pa je isti sajt jednom imao 179, a drugi put 281 zahtev. Sada se broje samo zahtevi
  započeti pre `load`; telo koje stigne kasnije za takav zahtev se broji. Ukupno je samo u
  tehničkoj rečenici i u JSON-u. Kad `load` ne stigne, težina je `unknown`. Snapshot nivoa 2 ima
  `requests_at_load`, `bytes_at_load`, `bytes_by_type_at_load` i `unmeasured_at_load`, a za
  snapshot iz 1.x obe provere su `unknown`.

- `seo.canonical.duplicate` je brojao i stranicu koja upućuje na sebe, pa su dve podstranice od
  sedam, sa canonical-om na početnu, davale `critical`. Sada se broje samo stranice sa tuđim
  canonical-om (bar dve, iz dve grupe putanja), a ozbiljnost zavisi od njihovog udela u uzorku:
  `medium`, `high` od 0,4, `critical` od 0,6. Rečenica kaže koliko od koliko proverenih stranica.

- Sajt sa jednom ili dve stranice bio je `partial`, jer provere duplikata nisu imale šta da
  uporede. Sada su `not_applicable`, ali samo kad sajt stvarno nema više stranica. Kad je uzorak
  mali zbog budžeta ili veza iz JavaScript-a, ostaju `unknown`, sa razlogom.

- Kad početna ne stigne do `load` za 25 s, rečenica je tvrdila „treba joj 25 s da se do kraja
  učita", a treba joj više. Sada kaže da se ni za 25 s nije do kraja učitala.
- Rečenice bez izvora: `infra.tls.invalid` više ne tvrdi da se većina posetilaca vrati sa
  upozorenja, a `infra.robots.missing` ne tvrdi da taj fajl svaki pretraživač prvo traži, nego da
  ga Google čita pre obilaska sajta. Test sada zabranjuje reči koje tvrde učestalost ili ponašanje
  ljudi (`većina`, `uvek`, `svaki`, `most`, `always`, `every`…) u rečenicama oba jezika.
- U HTML izveštaju je pisalo „1 nalaza"; sada se broj i imenica slažu („1 nalaz", „3 nalaza").
- HTML izveštaj na srpskom pisao je skor, bodove, trajanje i brzinu iz pretpostavke sa decimalnom
  tačkom („99.4"), a rečenice za klijenta sa zarezom. Sada svaki takav broj ide kroz formatter
  jezika („99,4" na srpskom, „99.4" na engleskom), sa jednom decimalom. Tehnička rečenica, dokaz,
  CSV i JSON ostaju mašinski zapis, sa tačkom i punom preciznošću.
- Bez instaliranog Playwright-a (`pip install skener` bez `[browser]`) prolaz sa nivoom 2 je
  pucao. Sada se nivo 2 preskače uz poruku, a nivo 1 radi.

## 1.0.0 — 24.09.2026.

Prvo izdanje: 28 provera na dva nivoa (sirovi HTTP i pravi browser), bodovanje po delatnosti,
rangiranje, HTML i CSV izveštaj sa rečenicama za klijenta na srpskom, `recheck` nad sačuvanim
snapshotima i identitet operatera u User-Agent-u. Provereno u tri prolaza nad 100 pravih domena
([IT-SKENER-002](docs/izvestaj-testiranja-2.md)).
