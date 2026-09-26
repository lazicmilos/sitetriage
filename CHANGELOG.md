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

### Dodato

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

### Ispravljeno

- Ključ pristojnosti bio je tačan host, pa bi `www.x.rs` i `x.rs` mogli da dobiju dva zahteva
  istovremeno. Sada je ključ host bez vodećeg `www.`: oba dele red i pauzu.

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
- U HTML izveštaju je pisalo „1 nalaza"; sada se broj i imenica slažu („1 nalaz", „3 nalaza").
- Bez instaliranog Playwright-a (`pip install skener` bez `[browser]`) prolaz sa nivoom 2 je
  pucao. Sada se nivo 2 preskače uz poruku, a nivo 1 radi.

## 1.0.0 — 24.09.2026.

Prvo izdanje: 28 provera na dva nivoa (sirovi HTTP i pravi browser), bodovanje po delatnosti,
rangiranje, HTML i CSV izveštaj sa rečenicama za klijenta na srpskom, `recheck` nad sačuvanim
snapshotima i identitet operatera u User-Agent-u. Provereno u tri prolaza nad 100 pravih domena
([IT-SKENER-002](docs/izvestaj-testiranja-2.md)).
