# Izveštaj o testiranju — skener v2, kalibracija na listi A i validacija na listi B

```
Naziv dokumenta:  Izveštaj o testiranju — skener v2 (F0–F3, F5)
Oznaka:           IT-SKENER-003
Verzija:          1.0
Datum:            05.10.2026.
Autor:            Milos Lazic
Status:           Nacrt
```

| Verzija | Datum | Autor | Opis izmene |
|---|---|---|---|
| 1.0 | 05.10.2026. | Milos Lazic | v2 bez F4: kalibracija na listi A, validacija na listi B, ručna provera, recenzija kataloga, BUG-017 do BUG-026 |

## 1. Predmet i obim

- **Predmet:** skener na grani `main` (`fc8ed88` i ispravke od 05.10.), verzija `2.0.0.dev0`,
  Docker slika sa Playwright 1.56.0 (Chromium 141) i Python 3.12. Plan:
  [`plan-testiranja.md`](plan-testiranja.md) (PT-SKENER-001, v2.2). Zahtevi: specifikacija v2 (SP-SKENER-002), faze F0–F3 i F5.
- **Šta je rađeno:** implementacija F0–F3 (Z-01 do Z-33) sa testovima i regresijom posle svake
  izmene; merenje pokrivenosti; mutaciono testiranje v2 koda; statičko testiranje kataloga poruka;
  kalibracija pragova na listi A (Z-50); sistemski test na listi B (Z-51), ponovljen posle ispravki;
  prijemni test, ručna provera prvih 10 i poslednjih 5 na listi B (Z-52), u dva kruga.
- **Šta nije rađeno:** F4 (`skener diff` i `skener outcomes`), koji je vlasnik 27.09. pomerio posle
  ručne prodaje izveštaja. Nije izmereno ni trajanje za 200 domena na preporučenoj mašini (Z-32), a
  nisu ponovljeni ni mutaciono testiranje nad kodom posle 30.09. i provera pragova nad listom A
  posle BUG-019. Ispravke BUG-021 do BUG-026 (05.10.) potvrđene su testovima i `recheck`-om
  snimaka, a novi prolaz nad B, koji Z-51 traži posle ispravke defekta nađenog na B, još nije rađen.
- **Test podaci:** lista A je istih 100 domena kao u IT-SKENER-001 i IT-SKENER-002, i na njoj su
  kalibrisani pragovi. Lista B je 100 novih domena istog tipa (male firme i udruženja iz Srbije, sa
  dodeljenom delatnošću), bez ijednog zajedničkog domena sa A. Liste, rezultati po domenu i
  popunjeni obrasci ručne provere nisu u repozitorijumu, pa su ovde samo zbirni brojevi.

## 2. Okruženje

Automatizovani i mutacioni testovi: Windows 10, Docker Desktop (WSL2), slika `skener:dev`. Pravi
prolazi idu kroz istu sliku, a Z-33 pre nivoa 2 meri stvarnu vezu:

| Prolaz | Veza |
|---|---|
| lista A, prolaz H (27.09.) | brza veza na drugom računaru, 107 Mb/s |
| lista A, GitHub Actions (28.09.) | datacentar van Srbije, 763 Mb/s |
| lista B, prvi prolaz (03.10.) | brza veza na drugom računaru, 136,4 Mb/s |
| lista B, nivo 2 ponovljen (05.10.) | mobilni hotspot, 18,6 Mb/s; nivo 1 je iz prolaza od 03.10. |

Nivo 1: 16 domena odjednom, jedan zahtev odjednom ka istom sajtu (`www.x.rs` i `x.rs` su isti
sajt), pauza 0,5–1 s, budžet 19 zahteva i 40 s po domenu. Pun nivo 2: mrežni profil 4,8 / 1,5 Mb/s
i 150 ms, učitavanje do `load` jedan po jedan, 3 konteksta, rok 25 s, tvrd limit 60 s po domenu,
najviše 60 domena. Vreme učitavanja se meri samo kad je stvarna veza bar 9,6 Mb/s. Od BUG-020
ostali sajtovi sa početnom koja radi dobijaju lagani nivo 2: posle punog, bez profila i bez reda za
učitavanje. U ponovljenom prolazu nad B lagani nivo 2 je radio sa 3 konteksta.

## 3. Rezultati

### 3.1 Automatizovani testovi

| | Pre ciklusa (v1.0.0) | Posle |
|---|---|---|
| testovi bez mreže | 632 | 1073: 1072 prolazi, 1 namerno pada (`xfail`); 12 `live` isključeno po defaultu |
| trajanje u kontejneru | ~1 min 45 s | 3 min 42 s (sa merenjem pokrivenosti 3 min 47 s) |
| pokrivenost linija i grana | 97 % | 98 % (2784 naredbe, 35 nepokrivenih; 782 grane, 28 delimično) |
| `cli.py` / `config.py` / `fetch/http.py` / `fetch/browser.py` | 92 / 99 / 98 / 90 % | 98 / 99 / 98 / 93 % |
| ruff | čist | čist |

Slučajevi nose oznaku tehnike u imenu: 125 graničnih vrednosti (`gv-`), 73 klase ekvivalencije
(`ke-`), 61 tabela odlučivanja (`tab-`), 35 nevažećih klasa (`nv-`), 11 prelaza stanja (`st-`) i
12 pogađanja grešaka (`pg-`). U IT-SKENER-002 bilo ih je 94, 29, 29, 18, 7 i 7.

U odnosu na merenje posle F0 (25.09.) nijedan modul nije pao. Najniža pokrivenost je i dalje u
`fetch/browser.py`, 93 % (bilo 90 %). Novi moduli (`addresses`, `inputs`, `messages`, `pipeline`,
`report/json_out`) imaju 100 %.

Jedan slučaj namerno pada: `test_browser_ne_prati_preusmerenje_na_privatnu_adresu` (`xfail`,
strogo). Playwright-ov `route` ne vidi cilj preusmerenja, pa nivo 2 ovu zaštitu nema. Ograničenje
je opisano u [ADR-006](adr/ADR-006-ssrf.md), a u web fazi tu štiti egress filter.

### 3.2 Mutaciono testiranje

mutmut 3.2.3 nad celim paketom osim mrežnog sloja, CLI-ja, pipeline-a, modela, skladišta i
izveštaja (`[tool.mutmut]` u `pyproject.toml`). U IT-SKENER-002 obim su bili samo `checks/`,
`score.py` i `config.py`, a sada su tu i čitanje liste, klasifikacija adresa i katalog poruka.
Pokretanje: `docker compose run --rm skener python scripts/mutacije.py`, 1107 s.

Prvo pokretanje nad v2 kodom puklo je pre prvog mutanta: mutmut u svoju kopiju prenosi samo `.py`
fajlove, pa je testovima nedostajala JSON šema. Šema se sada kopira (`also_copy`). Test koji čita
izvor paketa se pod mutmut-om preskače, jer izvor u kopiji sadrži i sve mutante.

| Modul | Mutanata | Preživelo |
|---|---|---|
| `score` | 228 | 1 |
| `messages` | 138 | 0 |
| `config` | 134 | 0 |
| `inputs` | 123 | 3 |
| `checks/registry` | 105 | 21 |
| `checks/seo` | 88 | 0 |
| `addresses` | 49 | 0 |
| `checks/i18n` | 46 | 0 |
| `checks/infra` | 18 | 5 |
| `checks/perf` | 15 | 0 |
| `checks/social` | 2 | 0 |
| **ukupno** | **946** | **30** (916 ubijeno, 96,8 %) |

Preživeli su razvrstani kao u IT-SKENER-002:

- 21 je u dekoratoru `check(...)` u registru. On radi pri importu, pre nego što mutmut uključi
  mutanta. Svaki je primenjen ručno na kopiju koda, a testovi su pokrenuti u novom procesu: svih 21
  je ubijeno.
- Za ostalih 9 dodata su četiri testa. Dokaz `adrese` kod `infra.host.duplicate` proveravao je samo
  golden test rečenica, koji nalaze računa pri importu, pa ga mutmut nije vezao za funkciju.
  Nijedan test nije razlikovao početnu adresu od konačne kad početna preusmerava na `www`. Lista
  izuzetih domena u windows-1250 i detalj greške u razlogu „Nije skenirano” nisu bili testirani.
  Ručnom primenom 7 je ubijeno.
- 2 su ekvivalentna: `split('#', 2)[0]` umesto `split('#', 1)[0]` daje isti prvi deo, a
  `url or host_of(url)` umesto `url and host_of(url)` daje isto, jer `normalize()` vraća `None` ili
  adresu sa hostom.

**Mutacioni skor: 944 od 944 neekvivalentnih, 100 %.** Ako se ekvivalentni računaju kao preživeli,
(916 + 28) / 946 = 99,8 %. Kriterijum je ≥ 90 %.

Dva ograničenja ovog broja:

- Mereno je nad kodom od 30.09. (`a9cbabb`). Ispravke BUG-017 do BUG-020 i Z-32 posle toga su
  menjale 7 fajlova iz obima (`checks/infra`, `checks/perf`, `checks/registry`, `config`,
  `messages/sr`, `messages/en`, `score`). Nad `fc8ed88` mutaciono testiranje nije ponovljeno.
- mutmut 3.2.3 ne pravi mutante za funkciju sa dekoratorom. Na vrhu modula menja samo definicije
  funkcija i klasa, a funkciju sa dekoratorom prepisuje nepromenjenu. Zato telo nijedne od 30
  provera (`@check(...)`) nije mutirano, ni u v1 ni u v2. Mutanti u `checks/*` su samo u pomoćnim
  funkcijama (`_tier`, `_duplicates`, `detect_language` i slične). Logiku samih provera pokrivaju
  granične vrednosti i tabele odlučivanja, ali mutaciono testiranje je nije izmerilo.

### 3.3 Statičko testiranje: katalog poruka

Od Z-12 rečenice za klijenta žive u katalogu, odvojene od provera, na srpskom i engleskom
([ADR-009](adr/ADR-009-katalog-poruka.md)). Po jeziku katalog ima 33 rečenice za klijenta (30
provera, tri sa varijantom), 46 razloga za „ne zna se” i 52 oznake izveštaja i nacrta mejla, ukupno
131 stavku.

Šta čuvaju testovi:

- katalog je potpun za oba jezika, a svaki kod razloga iz koda postoji u katalogu;
- golden fajl, napravljen pre refaktora, sada čuva 96 srpskih rečenica, pa refaktor nije mogao
  neprimetno da ih promeni (`test_srpske_recenice_iste_kao_pre_refaktora`);
- rečenica ne sme da sadrži reč koja tvrdi učestalost ili ponašanje ljudi: 8 reči za srpski
  (`većina`, `uvek`, `svaki` …) i 7 za engleski (`most`, `always`, `every` …), za svaku proveru i
  oba jezika (Z-27). Tako su ispravljene dve rečenice koje recenzija u IT-SKENER-002 nije videla:
  `infra.tls.invalid` („Većina se na toj strani vrati nazad”) i `infra.robots.missing` („svaki
  pretraživač prvo traži”);
- ispravljena netačna tvrdnja se ne vraća (`test_ispravljena_netacna_tvrdnja_se_ne_vraca`, sada i
  za BUG-018).

Prolaz nad B ipak je našao dve greške u rečenicama koje testovi nisu videli: BUG-017 (broj adresa
ne odgovara spisku) i BUG-018 („JavaScript greške” i kad greška nije iz skripte).

**Recenzija vlasnika (05.10.).** Svih 131 stavka je ocenjena po pravilima iz plana: tvrdnja se može
proveriti, svaki broj dolazi iz dokaza, nema tvrdnji o ponašanju ljudi bez izvora, a engleska
rečenica ne tvrdi više od srpske. Predlog ocena je pripremio Claude, a vlasnik ga je potvrdio.

| Ishod | Stavki | Šta |
|---|---|---|
| OK | 111 | — |
| ispravka | 15 | h1, alt i lang se mere samo na početnoj, pa to i piše; lažni 404 „odgovara kao da stranica postoji"; ponovljen naslov i opis ne tvrde kako izgledaju u Google rezultatima; pogrešan zapis `lang` nije „bez jezika"; tri razloga, dva engleska prevoda, pretpostavka u izveštaju i tvrdnja o `robots.txt` |
| pitanje za vlasnika | 5 | „mnogi posetioci ne čekaju toliko" (4 rečenice) i „Viber grupe" (og:image) nemaju izvor: izbačeni su, a „mnogi" i „često" su dodati na listu reči koje traže izvor |

Ispravljene tvrdnje čuva `test_ispravljena_netacna_tvrdnja_se_ne_vraca`, sada nad celim katalogom
(rečenice, razlozi i tekstovi izveštaja). Golden fajlovi su napravljeni ponovo, a razlika su samo
ove rečenice.

Recenzija je otkrila i četiri provere koje padaju tamo gde tačna rečenica ne važi. To su defekti u
kodu, ne u katalogu (BUG-023 do BUG-026, §5).

### 3.4 Kalibracija na listi A (Z-50)

Ulaz je prolaz H, bez novog skeniranja ([kalibracija](kalibracija.md), 28.09.). Pod profilom je
mereno 60 sajtova: 58 je stiglo do `load`, a 2 prekida su računata kao 25 s.

| | p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|---|
| težina do `load` bez videa | 2,2 MB | 3,6 MB | 7,3 MB | 8,7 MB | 13,4 MB |
| zahteva do `load` | 57 | 87 | 130 | 185 | 310 |
| vreme do `load` pod profilom | 5,6 s | 9,3 s | 15,2 s | 22,1 s | ≥ 25 s |

Pragovi su zaokruženi p50, p75 i p90, isti postupak kao u v1:

| Prag | Bilo | Sada | Nalaza u prolazu H, pre → posle |
|---|---|---|---|
| težina (medium / high / critical) | 3 / 5 / 8 MB | 2 / 4 / 7 MB | 20 → 32 |
| zahteva (medium / high) | 100 / 150 | 60 / 90 | 11 → 28 |
| vreme (medium / high) | 4 / 8 s | 6 / 9 s | 42 → 25 |

- Rok nivoa 2 ostaje 25 s (p95 je 22,1 s), a tvrd limit 60 s. Najduži nivo 2 po domenu bio je
  31,4 s na A (prolaz sa GitHub-a) i 31,9 s na B.
- `seo.canonical.duplicate`: oba nalaza na A provereni su `curl`-om. Jedan je stvaran. Drugi je
  nastao jer je poređenje računalo `http`/`https` i vodeće `www.` iste stranice kao drugu adresu, pa
  se takav canonical više ne broji. Granice udela 0,4 i 0,6 ostaju početne. Na B ovog nalaza nema.
- Posle `recheck`-a sa novim pragovima prvih 10 su isti sajtovi kao u prolazu H.
- Z-24 i Z-31, ponovljeni sa brze veze: težina i broj zahteva do `load` u granici od 10 % kod 10
  od 10 sajtova (najviše 5,7 %); odnos „u prolazu / sam” u opsegu 0,8–1,25 kod 19 od 20 merenja.
  `browser.serial_load` ipak ostaje `true`, jer uslov iz Z-31 traži svih 20.
- Posle Z-50 pragovi su zamrznuti. Otisak konfiguracije (`config_digest` `d989300e88ef`) isti je u
  `recheck`-u posle Z-50 i u svim izveštajima nad B.

Prolaz nad A sa GitHub Actions završen je bez pada i bez WARNING-a i ERROR-a u logu. Težina i broj
zahteva do `load` poklapaju se sa prolazom H (p50 2,1 MB i 56, prema 2,2 MB i 57). Ali u „Ne rade”
je 13 domena, a u H 7, pa taj prolaz ne važi za Z-51 (O-14).

### 3.5 Sistemski test na listi B (Z-51)

| | A, prolaz H | B, 03.10. | B, nivo 2 ponovljen 05.10. |
|---|---|---|---|
| nivo 1 / nivo 2 | 168 / 500 s | 145 / 460 s | 145 s (iz 03.10.) / 498 s, lagani 168 s |
| kandidata za nivo 2 / mereno | 81 / 60 | 91 / 60 | 91 / 60 punim i 40 laganim |
| rangiranih bez nivoa 2 | 30 | 40 | 0 |
| `scanned` / `partial` / `failed` / `unreachable` | 69 / 21 / 3 / 7 | 79 / 21 / 0 / 0 | 75 / 25 / 0 / 0 |
| `partial` zbog budžeta, među domenima koji rade | 7,8 % | 9,0 % | 9,0 % |
| `unknown` po proveri, najviše | 11,7 % | 5,0 % | 5,0 % |
| nalaza | 388 | 473 | 547 |
| padovi; WARNING i ERROR u logu | 0; 0 | 0; 0 | 0; 0 |
| procena za 200 domena | 13,9 min | 12,5 min | oko 23 min (lagani nivo 2 sa 3 konteksta) |

Prolaz H i prvi prolaz nad B rađeni su pre BUG-019 i BUG-020. Ponovljen nivo 2 je rađen sa
ispravkama, a izveštaj je napravljen `recheck`-om sa kodom od 05.10. Skripta za ponovljen nivo 2
meri vezu i posle punog nivoa 2 i odbacuje merenje ako je veza pala ispod 9,6 Mb/s. Merenje nije
odbačeno. U logu ponovljenog nivoa 2 ima 211 redova, svi INFO. Među njima je 7 redova o
zahtevima koje je nivo 2 odbio: 6 ka hostovima bez DNS zapisa i 1 ka `localhost`-u, koji SSRF
zaštita ne otvara.

**Potvrdno testiranje na pravim sajtovima:**

- BUG-017: svi nalazi `infra.host.duplicate` u prvih 10 tačni su u oba kruga ručne provere (4 i 3).
- BUG-018: u prvih 10 nije bilo nalaza `qa.console.errors`, pa je ispravka potvrđena samo testom.
- BUG-019: oba netačna nalaza iz prvog kruga ručne provere posle ispravke više ne postoje. Od prvih
  10 iz prvog kruga 9 je i dalje u prvih 10.
- BUG-020: rangiranih domena bez nivoa 2 bilo je 40, a sada ih nema. Domena sa 0 nalaza bilo je 8,
  a sada su 3. Nalaza je 547 umesto 473, najviše za težinu (37 → 56), broj zahteva (30 → 53),
  prevelike slike (28 → 47) i h1 (15 → 23). Obe teške strane sa dna liste iz prvog kruga sada imaju
  `perf.page.weight` (high) i više nisu na dnu.
- BUG-020, drugi deo: u ponovljenom prolazu `partial` je prvo skočio sa 21 na 54, jer je lagani
  nivo 2 vreme učitavanja beležio kao `unknown`. Kod 29 domena to je bio jedini uzrok. Posle
  izmene (vreme na laganom nivou 2 „ne primenjuje se”) `partial` je 25, a rangiranje i `findings.csv`
  su isti kao pre izmene.

### 3.6 Prijemni test: ručna provera (Z-52)

| | Prvi krug (04.10.) | Drugi krug (05.10.) |
|---|---|---|
| izveštaj | prolaz od 03.10. | nivo 1 od 03.10., nivo 2 od 05.10. |
| nalaza u prvih 10 | 98 | 89 |
| tačnih / netačnih | 96 / 2 | 89 / 0 |
| provereno urllib-om / skriptom u browseru | 62 / 36 | 54 / 35 |
| „poslao bih”: da / možda / ne | nije popunjeno | 7 / 2 / 1 |
| promašen ozbiljan problem u poslednjih 5 | 2 | 0 |

Nalaz je proveren van alata: sirovi HTML i zaglavlja preko urllib-a, a težina, zahtevi, vreme do
`load`, h1, alt i prevelike slike skriptom u browseru, pod istim profilom. Kod nalaza o jeziku
oznaka je proverena urllib-om, a tekst skriptom (4 nalaza u drugom krugu). Svaki netačan nalaz i
svaki promašaj prošao je kroz BUG proceduru: prvi krug je našao BUG-019 (2 netačna nalaza, isti
sajt) i BUG-020 (2 promašaja). Posle ispravki kriterijumi su ponovo izmereni na B, kako Z-51 traži.

U drugom krugu svih 5 sa dna liste alat je merio u browseru, jer od BUG-020 nijedan rangiran sajt
nije bez nivoa 2, i nijedan nema ozbiljan problem. Skripta je izmerila najtežu početnu od 1,9 MB i
najduže učitavanje od 5,0 s, a svih 5 radi na https-u. Odluke o
mejlu predložio je Claude posle pregleda snimaka ekrana sa telefona, a vlasnik ih je potvrdio
05.10. Poslednjih 5 je pregledano na istim snimcima i skriptom u browseru.

**Pouzdanost pomoćnih skripti.** Skripta za merenje u browseru testirana je pre upotrebe kao
poseban proizvod (izveštaj ostaje u `rad/`): 139 slučajeva po istim tehnikama, pokrivenost grana
99 % i 48 od 48 ručnih mutanata ubijeno. Nađeno je 13 defekata (1 blocker, 5 major, 5 minor, 2
trivial), i svi su ispravljeni pre merenja. Posle prvog kruga skripta je dopunjena i sada ima 141
slučaj. Između ostalog, slike sa drugog hosta bez `Timing-Allow-Origin` Performance API meri kao
0 bajtova, pa ih skripta sada meri iz mreže. Pomoćnik za sirovi HTML je 05.10. kod početne koja
nije stigla (DNS hotspota) potvrđivao nalaze tipa „nema opisa” nad praznom stranom. Ispravljen
je, provera je ponovljena i nema nijednog neslaganja. Nijedan od ovih defekata nije u alatu.

## 4. Izlazni kriterijumi

| Kriterijum | Granica | Rezultat | Ispunjen |
|---|---|---|---|
| automatizovani testovi | 100 % prolazi, u Docker slici i u CI-ju | 1072 / 1072 u Docker slici, 1 `xfail` po ADR-006; CI posle poslednjeg push-a ovde nije proveren | ✅ Docker, CI otvoreno |
| pokrivenost linija i grana | ≥ 95 %; nijedan modul ne pada; novi moduli ≥ 95 % | 98 %; nijedan modul nije pao; novi moduli 100 % | ✅ |
| mutacioni skor | ≥ 90 % neekvivalentnih; preživeli razvrstani | 100 % (strogo 99,8 %), kod od 30.09.; tela provera nisu mutirana (§3.2) | ✅ |
| `ruff` | čist | čist | ✅ |
| katalog poruka | potpun za `sr` i `en`; recenzija vlasnika urađena | potpun; recenzija 131 stavke urađena 05.10. (§3.3) | ✅ |
| JSON | izlaz prolazi šemu; `diff` istog izveštaja je prazan | šema: `test_json_izvestaj_prolazi_semu` prolazi; `diff` prebačen u F4 (§6.3) | ✅ šema, `diff` u F4 |
| SSRF | svi `gv-` i integracioni testovi prolaze | prolaze; jedno ograničenje po ADR-006 (`xfail`) | ✅ |
| padovi | 0 | 0 u svim prolazima nad A i B | ✅ |
| WARNING i ERROR u logu | 0 neobjašnjenih | 0 | ✅ |
| `partial` zbog budžeta | < 10 % domena koji rade | 9,0 % | ✅ |
| `unknown` po proveri | < 20 %; za vreme imenilac su sajtovi mereni pod profilom | najviše 5,0 % | ✅ |
| lažni nalazi | nijedan poznat | prvi krug 2 (BUG-019); drugi krug 0 od 89 u prvih 10. Van prvih 10: BUG-022 i BUG-023 (5 od 47 nalaza o slikama), ispravljeni 05.10. | ✅ u kodu; potvrda novim prolazom nad B |
| sajtovi koji ne rade u rangiranju | 0 | 0; na A 7 u „Ne rade”, potvrđeno DNS-om i `curl`-om; na B nijedan domen nije u „Ne rade” | ✅ |
| ponovljivost težine i broja zahteva do `load` | ≤ 10 % kod ≥ 9 od 10 sajtova | 10 od 10, najviše 5,7 % | ✅ |
| vreme u prolazu / vreme kad se sajt meri sam | 0,8–1,25, ako je paralelno učitavanje uključeno | ne primenjuje se: `serial_load = true`; uporedo 19 od 20 u opsegu | — |
| procena za 200 domena | ≤ 15 min | A 13,9 min i B 12,5 min bez laganog nivoa 2; sa njim oko 23 min na 3 konteksta; preporučena mašina nije merena | otvoreno |
| prvih 10 na B | 0 netačnih; ≥ 7 od 10 „poslao bih” | 0 od 89; 7 od 10 | ✅ |
| poslednjih 5 na B | 0 promašenih; posle ispravke se meri ponovo | prvi krug 2 (BUG-020); posle ispravke 0 | ✅ |
| otvorena zapažanja | O-5 i O-7 do O-12 zatvoreni ili prebačeni u §9 specifikacije | svi zatvoreni ili prebačeni (§6.1) | ✅ |

## 5. Defekti

| ID | Naslov | Ozbiljnost | Kako je nađen | Potvrdni test | Status |
|---|---|---|---|---|---|
| BUG-017 | Broj adresa u rečenici o duplikatu hosta ne odgovara spisku | major | sistemski test B, pregled rečenica | `test_broj_adresa_u_recenici_odgovara_spisku` | Zatvoren |
| BUG-018 | Rečenica o konzoli sve greške naziva „JavaScript greške” | major | sistemski test B, pregled rečenica | `test_ispravljena_netacna_tvrdnja_se_ne_vraca[sr-konzola-nije-samo-javascript]` | Zatvoren |
| BUG-019 | Nivo 2 se ne predstavlja kao browser, pa reklame i fontovi stižu teži | major | ručna provera Z-52, prvi krug | `test_browser_se_predstavlja_svojim_user_agentom_uz_identitet_operatera` | Zatvoren |
| BUG-020 | Teška strana bez razloga za eskalaciju ne ide u browser | major | ručna provera Z-52, poslednjih 5 | `test_sajt_van_limita_dobija_lagani_nivo_2`, `test_vreme_na_laganom_nivou_2_se_ne_primenjuje` | Zatvoren |
| BUG-021 | Nivo 2 ne proverava HTTP status glavnog dokumenta | major | pregled snimaka nivoa 2 za ovaj izveštaj | `test_strana_greske_na_nivou_2_je_neuspelo_snimanje` | Ispravljen; potvrda na B čeka prolaz |
| BUG-022 | Nivo 1 ne prati preusmerenje samo JavaScript-om ili meta-refresh-om na isti sajt | major | ručna provera Z-52, drugi krug | `test_pocetna_koja_preusmerava_skriptom_je_skok_kao_http_preusmerenje` | Ispravljen; potvrda na B čeka prolaz |
| BUG-023 | Prevelike slike broje SVG i `data:` čuvare mesta, a nalaz pada i bez izmerenog prenosa („oko 0 kB") | major | recenzija kataloga | `test_svg_i_data_slike_nisu_prevelike`, `test_prevelike_slike_bez_izmerenog_prenosa_su_unknown_a_ne_0_kb` | Zatvoren (`recheck`) |
| BUG-024 | Nepotpun lanac sertifikata je nalaz da posetilac vidi upozorenje | major | recenzija kataloga | `test_nepotpun_lanac_sertifikata_je_unknown` | Zatvoren |
| BUG-025 | Tekst na ruskom, makedonskom ili hrvatskom sa ispravnim `lang` dobija „sadržaj je na srpskom" | major | recenzija kataloga | `test_jezik_istog_pisma_nije_mismatch` | Zatvoren |
| BUG-026 | Mrtva prva mapa iz `robots.txt` uz drugu koja radi daje „Sajt nema mapu stranica" | major | recenzija kataloga | `test_mrtva_prva_mapa_uz_drugu_koja_radi_nije_nalaz` | Zatvoren |

Ozbiljnost je dodeljena po definicijama iz plana testiranja (§8): lažan nalaz ili lažno negativan
rezultat za klijenta je major. BUG-017 je na B pogodio 16 od 23 nalaza `infra.host.duplicate` (na A
6 od 14), a BUG-018 3 od 6 nalaza `qa.console.errors`. BUG-023 je na B dao 5 lažnih od 47 nalaza
`perf.img.oversized` (na A 2 od 23), a kod još 15 broj slika je bio preveliki; nijedan nije bio u
prvih 10. BUG-024 do BUG-026 u prolazima nisu viđeni, ali rečenica bi u tim slučajevima tvrdila
nešto netačno. Ceo skup testova prolazi posle svih ispravki (§3.1).

`recheck` snimaka liste A i B sa ispravkama BUG-023 do BUG-026 daje istih prvih 10. Nestali su
samo nalazi o slikama koji su poticali od SVG i `data:` slika, a jedan je postao `unknown`.

Defekte BUG-017 do BUG-022 našla je provera na pravim sajtovima, a BUG-023 do BUG-026 recenzija
kataloga, kad je za svaku rečenicu pitala da li važi u svakom slučaju u kome provera pada. Grupišu
se oko nivoa 2 (BUG-019, BUG-020, BUG-021), rečenica za klijenta (BUG-017, BUG-018) i uslova pod
kojim provera pada (BUG-022 do BUG-026). BUG-021 je nastao iz ispravke BUG-019, pa izmena u tome
kako se alat predstavlja sajtu u sledećem ciklusu ide uz pregled snimaka, ne samo nalaza.

```
ID: BUG-021   Naslov: Nivo 2 ne proverava HTTP status glavnog dokumenta
Ozbiljnost: major   Prioritet: high
Okruženje: main (fc8ed88), Docker, Windows 10; ponovljen nivo 2 nad listom B, 05.10.2026.
KORACI ZA REPRODUKCIJU
 1. Sajt čija zaštita od botova odbija User-Agent sa „HeadlessChrome” i vraća 403 sa kratkom
    stranicom greške, a zahtev nivoa 1 pušta (200).
 2. Pokrenuti nivo 2 nad tim sajtom.
OČEKIVANO   Glavni dokument sa statusom ≥ 400 je neuspelo snimanje; provere nivoa 2 su `unknown`
            sa razlogom.
STVARNO     Snimak je `ok` i stigao je do `load`: 1 zahtev, 358 B. Stranica greške se meri i
            ocenjuje kao početna.
UČESTALOST  1 od 220 snimaka nivoa 2 (lista A, prolaz H: 60; lista B: 60; lista B ponovljeno: 100)
NAPOMENA    U prvom prolazu nad B, sa starim UA, isti sajt je izmeren normalno: 106 zahteva, oko
            2 MB. Od BUG-019 browser šalje UA koji Chromium sam prijavljuje („HeadlessChrome/…”),
            uz identitet operatera, i zaštita tog servera ga odbija. Lažnog nalaza nije bilo, jer
            je stranica greške mala i ima h1, ali prava težina nije izmerena. Stranica greške bez
            h1 dala bi lažan nalaz. Odluka vlasnika (05.10.): status ≥ 400 je neuspelo snimanje, a
            UA gubi „Headless” i zadržava identitet operatera.
STATUS      Ispravljen 05.10. (greška `http_status`, provere nivoa 2 `unknown`; UA „Chrome/…").
            Potvrda na pravom sajtu čeka novi prolaz nad B.
```

## 6. Zapažanja i odluke

### 6.1 Zapažanja iz IT-SKENER-001 i IT-SKENER-002

| Zapažanje | Zahtev | Kako je zatvoreno | Status |
|---|---|---|---|
| O-5: sajt koji ne odgovara nema nalaz | Z-20 | nalaz `infra.unreachable` i lista „Ne rade”; na A 7 domena u „Ne rade”, svih 7 potvrđeno DNS upitom i `curl`-om | zatvoreno |
| O-7a: sajt sa < 3 stranice je `partial` | Z-21 | `not_applicable` samo kad sajt stvarno ima < 3 stranice. Od 5 takvih domena 1 je dopunom vezama dobio 7 stranica, a peti je ostao bez budžeta i `partial`, kako Z-21 traži. Tri zaista imaju 1–2 stranice i provere duplikata su im `not_applicable`, ali ostaju `partial` zbog drugih provera | zatvoreno, po tumačenju vlasnika (27.09.) |
| O-7b: kriterijum `partial` < 10 % | Z-22 | podeljen: budžet 9,0 %, `unknown` po proveri najviše 5,0 % (B) | zatvoreno |
| O-7: tekst iz JavaScript-a | Z-25 | jezik iz renderovanog teksta. Sva 3 sajta su prošla nivo 2, ali ni posle JS-a nemaju 400 znakova teksta (strana sa jednim dugmetom, strana „u pripremi”, samo podnožje), pa je `unknown` tačan odgovor | zatvoreno, po tumačenju vlasnika (27.09.) |
| O-7: lenje učitane slike | — | ostaje `unknown` | prebačeno u §9 |
| O-7: sonde za lažni 404 bez zaključka | — | ostaje `unknown` | prebačeno u §9 |
| O-8: domeni bez DNS-a u vrhu liste | Z-20 | izlaze iz rangiranja u „Ne rade” | zatvoreno |
| O-9: `seo.canonical.duplicate` broji početnu | Z-23, Z-50 | broji se samo tuđi canonical, ozbiljnost po udelu; na A 1 stvaran nalaz, proveren `curl`-om | zatvoreno |
| O-10: stranica učitava i posle `load` | Z-24 | težina i zahtevi do `load`; 10 od 10 u granici od 10 % | zatvoreno |
| O-11: decimalna tačka u HTML-u | Z-28 | `test_html_na_srpskom_nema_decimalnu_tacku_u_tekstu` | zatvoreno |
| O-12: `optional` ne koristi nijedna provera | Z-26 | `optional` obrisan; kanonizacija hosta su dve nove provere, uz budžet od 19 zahteva. U prolazu E budžet je potrošilo 9 domena, a dozvoljeno je 8. Vlasnik je to prihvatio uz analizu uzroka, a u prolazu H ih je 7 | zatvoreno |
| O-13: ispravka IT-SKENER-001 | — | samo ispravka izveštaja | bez rada |

### 6.2 Nova zapažanja

- **O-14: lista „Ne rade” zavisi od adrese sa koje se skenira.** U prolazu sa GitHub Actions u
  „Ne rade” je bilo 6 domena koji su dan ranije, u prolazu H, skenirani. Nisu prihvatali vezu ni
  na 443 ni na 80, u oba pokušaja.
  Pet ih je kod istog hostinga u Srbiji, a sa kućne adrese pet od šest odgovara. Hosting odbacuje
  veze iz datacentra van Srbije, a alatu to izgleda isto kao ugašen server, pa nacrt mejla vlasniku
  kaže da mu sajt ne radi. Odluka: prolaz za Z-51 ide sa adrese u Srbiji. Za web fazu i za VPS ovo
  ostaje rizik.
- **O-15: početna skoro bez sadržaja nije nalaz.** Od 160 početnih strana merenih u browseru (lista
  A 60, lista B 100) 4 imaju manje od 200 znakova vidljivog teksta, a 7 manje od 400. Jedna od te 4
  je stranica greške iz BUG-021. Takva početna je u prvih 10 na B bila jedan od razloga za „poslao
  bih”, ali je alat ne prijavljuje. Odluka: nova provera, posle v2 (§6.3).
- **O-16: strana „u pripremi” i parkiran domen bez preusmerenja.** Alat ih ocenjuje kao obične
  sajtove. Koliko ih je na A i B nije izmereno. Ostaje zapažanje. Varijantu sa preusmerenjem
  JavaScript-om ili meta-refresh-om rešava BUG-022: nad snimcima A i B pravilo hvata samo stranu
  zbog koje je defekt prijavljen, a nijednu drugu.
- **O-17: rangiranje ne zna da li je sajt firma.** U prvih 10 na B jedno „ne” je udruženje, a ne
  firma, iako su svi njegovi nalazi tačni. Dva „možda” su firma koja posao dobija preko tendera, a
  ne preko sajta, i nov, uredan sajt kome je jedini jak argument brzina. Zaključak ručne provere:
  izbor domena je posao kupca koji pravi listu, a ne alata.
- **O-18: trajanje sa laganim nivoom 2 (Z-32).** Pun nivo 2 ostaje na 60 domena, pa na 200 domena
  lagani nivo 2 dobija oko 140 sajtova. Sa merenjem nad B i 3 konteksta procena je
  290 + 498 + 140 × 4,2 ≈ 1376 s, oko 23 min, a granica je 15. Odluka vlasnika: lagani nivo 2 bira
  broj konteksta po mašini (jedan na svaki slobodan GB, najviše dva po jezgru i najviše 8), a
  granica od 15 min važi za preporučenu mašinu, sa 16 GB RAM-a i vezom od bar 50 Mb/s. Na takvoj
  mašini trajanje još nije izmereno (§6.3, odluka 6).
- **O-19: naslov, opis i canonical postavljeni JavaScript-om.** Nivo 1 ih čita iz sirovog HTML-a, a
  Google izvršava JavaScript, pa bi kod takvog sajta `seo.title.missing`, `seo.description.missing` i
  `seo.canonical.missing` bili lažni. Koliko je takvih sajtova nije poznato. Odluka vlasnika (05.10.):
  nivo 2 ih za sada samo beleži (`dom.title`, `dom.meta_description`, `dom.canonical`), a o
  proverama se odlučuje posle sledećeg prolaza nad B.

### 6.3 Odluke vlasnika od 05.10.2026.

| # | Odluka | Status |
|---|---|---|
| 1 | BUG-021: glavni dokument nivoa 2 sa statusom ≥ 400 je neuspelo snimanje, pa su provere nivoa 2 `unknown`. UA gubi „Headless”, a identitet operatera ostaje | ispravljeno; potvrda na B čeka prolaz |
| 2 | BUG-022: nivo 1 prati preusmerenje samo JavaScript-om ili meta-refresh-om na isti sajt kao HTTP preusmerenje. Strana „u pripremi” i parkiran domen bez preusmerenja ostaju zapažanje (O-16) | ispravljeno; potvrda na B čeka prolaz |
| 3 | Nova provera „početna skoro bez sadržaja” (O-15), kalibrisana na A i B | u README-u, „Planirano, nije u v2” |
| 4 | [ADR-011](adr/ADR-011-json-sema.md) (`report.json` kao ugovor sa šemom i verzijom) postaje „Prihvaćeno” | urađeno |
| 5 | Kriterijum „`diff` istog izveštaja je prazan” prelazi u F4, pa izdanje v2.0.0 ne čeka na njega | urađeno (plan testiranja v2.2) |
| 6 | Z-32 na preporučenoj mašini meri se pri prvom prolazu na VPS-u, pre prvog plaćenog izveštaja | otvoreno |
| 7 | Recenzija kataloga: 15 ispravki; rečenice o ponašanju ljudi bez izvora se izbacuju; BUG-023 do BUG-026 se ispravljaju odmah | urađeno |
| 8 | Naslov, opis i canonical posle JavaScript-a nivo 2 samo beleži (O-19) | urađeno; odluka posle prolaza nad B |
| 9 | Mutaciono testiranje tela provera (§3.2) | sledeći ciklus; ne blokira v2 |

## 7. Zaključak i preporuka

Alat je stabilan i na novoj listi. Nijedan prolaz nad A i B nije pao, a u logu nema nijednog
WARNING-a ni ERROR-a. Na B su ispunjeni svi merljivi kriterijumi tačnosti: `partial` zbog budžeta
9,0 %, `unknown` po proveri najviše 5,0 %, a u drugom krugu ručne provere 0 netačnih od 89 nalaza
u prvih 10, 7 od 10 „poslao bih” i nijedan promašaj u poslednjih 5.

Do toga se došlo tek posle ispravki. Prvi krug je našao 2 netačna nalaza i 2 promašaja. Uzrok
nije bio u pragovima, nego u nivou 2: u tome kako se alat predstavlja sajtu (BUG-019) i u tome koji
sajtovi idu u browser (BUG-020). Pragovi iz Z-50 posle toga nisu menjani.

Recenzija kataloga je urađena. Uz 15 ispravki rečenica našla je četiri provere koje padaju tamo
gde rečenica ne važi (BUG-023 do BUG-026). Ispravljene su odmah, kao i BUG-021 i BUG-022.

Otvoreno je:

- novi prolaz nad B, koji potvrđuje BUG-021 i BUG-022 na pravim sajtovima i ponovo meri kriterijume,
  kako Z-51 traži;
- trajanje za 200 domena na preporučenoj mašini (Z-32), koje se meri na prvom prolazu sa VPS-a, pre
  prvog plaćenog izveštaja, pa izdanje v2.0.0 ne čeka na njega;
- stanje CI-ja posle poslednjeg push-a, koje ovde nije provereno.

**Preporuka: izdanje v2.0.0 je opravdano kad novi prolaz nad B ispuni kriterijume iz §4 i CI bude
zelen.** Mutaciono testiranje tela provera (§3.2) nije uslov iz §4 i ide u sledeći ciklus.

## 8. Naučene lekcije

- Ispravka može da otvori nov defekt. Posle BUG-019 alat se sajtu predstavlja drugačije, i bar
  jedan server ga sada odbija (BUG-021). Pošto nivo 2 nije gledao status glavnog dokumenta,
  stranica greške je izgledala kao uspešno snimanje. Našao ju je tek pregled snimaka po broju
  zahteva i bajtova, a ne pregled nalaza.
- Testovi bez mreže ne vide ono što zavisi od sveta oko sajta. Reklamne mreže i fontovi koji biraju
  sadržaj po User-Agent-u (BUG-019) i teške strane sa čistim HTML-om (BUG-020) pokazale su se tek
  pri proveri van alata, na novoj listi.
- Alat kojim se proverava i sam je softver. Skripta za ručnu proveru imala je 13 defekata, od toga
  jedan blocker, a pomoćnik za sirovi HTML potvrđivao je nalaze nad praznom stranom. Skripta koja
  daje presudu testira se pre nego što joj se veruje.
- Kriterijum o trajanju mora da navede mašinu i vezu. Isti alat daje 12,5 min ili oko 23 min za 200
  domena, zavisno od veze, od toga koliko sajtova ide u browser i od broja konteksta, a kriterijum
  se pri tome nije promenio.
- Recenzija rečenica je i recenzija provera. Pitanje „da li ova rečenica važi u svakom slučaju u kome
  provera pada" našlo je četiri klase lažnih nalaza koje ni testovi ni ručna provera prvih 10 nisu
  videli, jer se u uzorku nisu pojavile ili nisu bile u vrhu liste.
- Visok mutacioni skor treba čitati uz spisak funkcija koje su mutirane. mutmut 3.2.3 ne mutira
  funkcije sa dekoratorom, pa je 100 % izmereno bez ijedne od 30 provera.
