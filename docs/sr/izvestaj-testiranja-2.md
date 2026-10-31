# Izveštaj o testiranju — ciklus ispravki i ponovljen prolaz nad 100 domena

```
Naziv dokumenta:  Izveštaj o testiranju — skener, ciklus ispravki
Oznaka:           IT-SKENER-002
Verzija:          1.0
Datum:            24.09.2026.
Autor:            Milos Lazic
Status:           Nacrt
```

| Verzija | Datum | Autor | Opis izmene |
|---|---|---|---|
| 1.0 | 24.09.2026. | Milos Lazic | Ispravke BUG-003 do BUG-016, sistematsko testiranje, dva ponovljena prolaza |

## 1. Predmet i obim

- **Predmet:** skener na grani `main` posle ispravki iz ovog ciklusa, Docker slika sa Playwright 1.56.0
  i Python 3.12. Plan: [`plan-testiranja.md`](plan-testiranja.md) (PT-SKENER-001).
- **Šta je rađeno:** potvrdno testiranje ispravki iz [IT-SKENER-001](izvestaj-testiranja-100.md);
  sistematsko testiranje tehnikama iz plana; merenje pokrivenosti; mutaciono testiranje; recenzija
  svih rečenica za klijenta; dva ponovljena prolaza nad istih 100 domena (regresija).
- **Šta nije rađeno:** prijemna ocena vrha liste. Nju radi vlasnik proizvoda (§7).
- **Test podaci:** ista lista od 100 domena kao u IT-SKENER-001. Lista i rezultati po domenu nisu u
  repozitorijumu, pa su ovde samo zbirni brojevi.

## 2. Okruženje

Windows 10, Docker Desktop, slika `skener:dev`, kućna internet veza. Nivo 1: 8 domena istovremeno,
pauza 0,5–1 s između zahteva ka istom sajtu, budžet 16 zahteva i 40 s po domenu. Nivo 2: 3 konteksta,
učitavanje do događaja `load` jedan po jedan, gornji limit 60 domena.

## 3. Rezultati

### 3.1 Automatizovani testovi

| | Pre ciklusa | Posle |
|---|---|---|
| testovi bez mreže | 327 | 632, svi prolaze (12 `live` isključeno po defaultu) |
| trajanje u kontejneru | ~40 s | ~1 min 45 s |
| pokrivenost linija i grana | 92 % | 97 % |
| `cli.py` / `config.py` / `fetch/http.py` / `fetch/browser.py` | 76 / 88 / 93 / 82 % | 92 / 99 / 98 / 90 % |
| ruff | čist | čist |

Slučajevi nose oznaku tehnike u imenu: 94 granične vrednosti (`gv-`), 29 klasa ekvivalencije (`ke-`),
29 tabela odlučivanja (`tab-`), 18 nevažećih klasa (`nv-`), 7 prelaza stanja (`st-`) i 7 pogađanja
grešaka (`pg-`).

### 3.2 Mutaciono testiranje

mutmut 3.2.3 nad `checks/`, `score.py` i `config.py`. Mrežni sloj, CLI i izveštaje pokrivaju
integracioni testovi. Pokretanje: `docker compose run --rm skener python scripts/mutacije.py`.

| Prolaz | Mutanata | Ubijeno | Napomena |
|---|---|---|---|
| prvi | 455 | 418 (91,9 %) | nijedan test nije proveravao formule u rečenicama (sekunde na mobilnoj vezi, ušteda od kompresije) ni izvor uzorka; testovi dodati |
| drugi | 460 | 431 (93,7 %) | 29 preživelih, razvrstani ispod |

Od 29 preživelih, 28 je u dekoratoru `check(...)` u registru. On se izvršava pri importu modula, a
mutmut 3 uključuje mutanta tek posle importa, pa te mutante ne može da ubije nijedan test. Zato je
svaki od njih primenjen ručno na kopiju koda, a testovi su pokrenuti u novom procesu:

- 26 ubijeno. Jedan od njih (`description=None`) preživeo je i ručnu proveru, jer je `skener explain`
  ispisivao opis provere, a nijedan test ga nije čitao. Dodat je `test_explain_ispisuje_opis_provere`.
- 2 ekvivalentna: `optional=None` i izostavljen `optional`. Nijedna provera nije registrovana kao
  opciona, pa se `None`, `False` i podrazumevana vrednost ponašaju isto.

Preostali preživeli je u `score.level1_score`: zaokruživanje na 5 umesto 4 decimale. Skor se
prikazuje na jednu decimalu, a množioci imaju najviše dve, pa je mutant ekvivalentan.

**Mutacioni skor: 457 od 457 neekvivalentnih, 100 %.** Ako se ekvivalentni računaju kao preživeli,
457 / 460 = 99,3 %. Kriterijum iz plana je ≥ 70 %.

### 3.3 Recenzija rečenica za klijenta (statičko testiranje)

Svih 28 rečenica pregledano je po tri pravila: tvrdnja mora da se proveri, svaki broj mora da potiče
iz dokaza, a broj i imenica moraju da se slažu. Tako su nađeni BUG-013, BUG-014 i BUG-015, i
ispravljeno je nekoliko preuveličanih tvrdnji:

| Bilo je | Zašto ne stoji | Sada |
|---|---|---|
| „većina posetilaca ne čeka toliko" | nema izvora za „većinu" | „mnogi posetioci ne čekaju toliko" |
| slike se preuzimaju „pri svakom učitavanju" | browser ih čuva u kešu | „pri prvoj poseti" |
| greške u konzoli „najčešće na starijim telefonima" | ništa u merenju to ne pokazuje | izbačeno |
| pogrešan `lang` znači da ga „pretraživači nude pogrešnom tržištu" | Google jezik određuje iz sadržaja | posledica je izgovor u čitaču ekrana |

Pravila čuva `tests/test_poruke.py`: test pada ako se u rečenici pojavi broj koji nije u dokazu ili
ako se vrati neka od ispravljenih tvrdnji.

### 3.4 Sistemski test nad 100 domena

Prolaz A je iz IT-SKENER-001. Prolaz B je rađen posle ispravki BUG-003 do BUG-015, a prolaz C posle
BUG-016, koji je nađen u prolazu B.

| | A | B | C |
|---|---|---|---|
| trajanje | 7 min 41 s | 10 min 3 s | 9 min 16 s |
| nivo 1 / nivo 2 | 211 / 246 s | 229 / 372 s | 217 / 337 s |
| `scanned` / `partial` / `failed` | 62 / 27 / 11 | 74 / 16 / 10 | 77 / 13 / 10 |
| `partial` među domenima koji rade | 30 % | 17,8 % | 14,4 % |
| domena sa potrošenim budžetom | 19 | 5 | 6 |
| padovi; WARNING i ERROR u logu | 0; 0 | 0; 0 | 0; 0 |

Nivo 2 traje duže nego u A, jer se do `load` učitava jedan po jedan (BUG-006). Za 200 domena procena
je oko 13 min: nivo 1 raste linearno, a nivo 2 je ograničen na 60 domena.

**Potvrdno testiranje na pravim sajtovima:**

- BUG-003: oba sajta iza zaštite od botova su `failed` bez ijednog nalaza, a robots.txt, mapa sajta
  i sonde za lažni 404 su `unknown` sa razlogom.
- BUG-004: sajt koji prekida TLS rukovanje sa Python klijentom skeniran je preko http-a. Sertifikat
  je `unknown` („https nije uspeo … sertifikat nije proveren").
- BUG-005: od 40 domena koji u A nisu stigli na nivo 2, sada je izmereno 11. Nijedan kandidat bez
  nalaza nije ostao nemeren.
- BUG-006: deset sajtova, raspoređenih po izmerenom vremenu, ponovo je izmereno jedan po jedan. Odnos
  vremena u prolazu i vremena kad se sajt meri sam je 0,72–1,24, a u ponovljenom merenju 0,82–1,22.
  U A je bio 1,07–4,63.
- BUG-016: isti sajt je pre ispravke imao 25,3 MB, a preneto je 3,8 MB. Kod još dva sajta 49,4 MB je
  postalo 7,4 MB, a 32,7 MB je postalo 3,4 MB. Nestali su i `unknown` za težinu, jer se sada meri i
  ono što ranije nije moglo.

**Nezavisna provera vrha liste:** za prvih 5 u rangiranju nalazi nivoa 1 provereni su van alata
(`curl`, sirovi HTML): nedostaje canonical (2 sajta), nedostaje `og:title` (4), nema `<h1>` u sirovom
HTML-u (4). Poklapa se u oba smera: alat prijavljuje tačno te sajtove, a kod ostalih curl nalazi
oznaku koju alat nije ni prijavio kao nedostajuću. Nalaz na prvom mestu (`seo.canonical.duplicate`)
je tačan, ali otvara pitanje kalibracije (O-9).

## 4. Izlazni kriterijumi

| Kriterijum | Granica | Rezultat | Ispunjen |
|---|---|---|---|
| automatizovani testovi | 100 % prolazi | 632 / 632 u Docker slici; CI posle push-a | ✅ |
| pokrivenost | ≥ 92 %, bez pada ni u jednom modulu | 97 %; nijedan modul nije pao | ✅ |
| pokrivenost `cli.py` | ≥ 85 % | 92 % | ✅ |
| granične vrednosti | svaki prag ima test granica − 1, granica, granica + 1 | 94 slučaja `gv-` | ✅ |
| mutacioni skor | ≥ 70 % | 100 % (strogo 99,3 %) | ✅ |
| otvoreni defekti | nijedan blocker, critical ni major | nijedan; BUG-016 (major) nađen i zatvoren u ovom ciklusu | ✅ |
| pravi prolaz: padovi | 0 | 0 u sva tri prolaza | ✅ |
| pravi prolaz: `partial` | < 10 % | **14,4 %** | ❌ |
| pravi prolaz: lažni nalazi | nijedan poznat | nijedan poznat | ✅ |
| procena za 200 domena | ≤ 15 min | ~13 min | ✅ |
| vreme učitavanja | u prolazu ≤ 1,3× vremena kad se sajt meri sam | 0,72–1,24× | ✅ |

## 5. Defekti

| ID | Naslov | Ozbiljnost | Kako je nađen | Potvrdni test | Status |
|---|---|---|---|---|---|
| BUG-003 | Sajt iza zaštite od botova dobija nalaze o robots.txt i mapi sajta | major | sistemski test A | `test_blokiran_sajt_nema_nijedan_nalaz` | Zatvoren |
| BUG-004 | Prekinuto TLS rukovanje se prijavljuje kao nevalidan sertifikat | major | sistemski test A, curl | `test_prekinuto_rukovanje_pada_na_http_a_sertifikat_ostaje_neproveren` | Zatvoren |
| BUG-005 | Limit nivoa 2 odseca kandidate bez nalaza nivoa 1 | major | sistemski test A | `test_limit_ne_odseca_sajt_kome_je_nivo_2_jedina_sansa` | Zatvoren |
| BUG-006 | Vreme učitavanja se meri dok tri sajta dele vezu | major | ponovljeno merenje | `test_ucitavanja_razlicitih_sajtova_se_ne_preklapaju` | Zatvoren |
| BUG-007 | Posle tvrdog limita asyncio u log upisuje grešku zatvorenog konteksta | trivial | integracioni test tvrdog limita | `test_prekid_posle_tvrdog_limita_ne_ostavlja_gresku_u_logu` | Zatvoren |
| BUG-008 | CSV iz Excel-a sa `;` nema kolonu `domain` | major | pogađanje grešaka | `test_csv_iz_excela_sa_tackom_zarezom` | Zatvoren |
| BUG-009 | CSV u windows-1250 obara alat | major | pogađanje grešaka | `test_csv_u_windows_1250` | Zatvoren |
| BUG-010 | Isti domen dva puta na listi skenira se dva puta | minor | pogađanje grešaka | `test_csv_duplikati_se_skeniraju_jednom` | Zatvoren |
| BUG-011 | Paralelizam 0 zaustavlja prolaz zauvek, bez poruke | major | granične vrednosti (0) | `test_paralelizam_i_budzet_moraju_biti_pozitivni` | Zatvoren |
| BUG-012 | Vreme u logu nosi „Z", a lokalno je | minor | pogađanje grešaka | `test_vreme_u_logu_je_zaista_utc` | Zatvoren |
| BUG-013 | Poruka o kompresiji tvrdi uštedu od „sekunde i po" | major | recenzija rečenica | `test_usteda_od_kompresije_se_racuna_iz_velicine` | Zatvoren |
| BUG-014 | Broj i imenica se ne slažu („4 JavaScript grešaka") | minor | recenzija, granične vrednosti | `test_srpski_broj` | Zatvoren |
| BUG-015 | Decimalna tačka u rečenici („14.9 MB") | trivial | recenzija rečenica | `test_brojevi_u_recenici_imaju_decimalni_zarez` | Zatvoren |
| BUG-016 | Težina stranice sabira raspakovane bajtove | major | sistemski test B | `test_tezina_broji_prenete_bajtove_a_ne_raspakovane` | Zatvoren |

Svaki potvrdni test je pao pre ispravke. Posle svake ispravke pokrenut je ceo skup (regresiono
testiranje). Defekti su se grupisali oko komandne linije (CSV, konfiguracija i log: 5 defekata) i
rečenica za klijenta (4, sa BUG-016), pa tamo treba tražiti i u sledećem ciklusu.

```
ID: BUG-016   Naslov: Težina stranice sabira raspakovane bajtove, a rečenica kaže „prenosi"
Ozbiljnost: major   Prioritet: high
Okruženje: main posle ispravki BUG-003–015, Docker, Windows 10
KORACI ZA REPRODUKCIJU
 1. Skenirati sajt čija početna učitava mnogo JavaScript-a i CSS-a koje server šalje sažete (gzip, br).
 2. Uporediti `network.total_bytes` sa onim što browser prikazuje kao preneto.
OČEKIVANO   Broj bajtova koji je stvarno stigao preko mreže.
STVARNO     Zbir raspakovanih tela: 25,3 MB umesto 3,8 MB. Rečenica „Početna strana prenosi 25 MB"
            i procena sekundi na mobilnoj vezi preuveličavaju oko 6 puta.
UČESTALOST  100 % za sajtove sa sažetim JS-om i CSS-om; kod slika i videa nema razlike
NAPOMENA    `_Recorder._measure` je koristio `len(response.body())`. Sada koristi `responseBodySize`
            iz `request.sizes()`. Pragovi 5 / 10 / 20 MB bili su kalibrisani nad raspakovanim
            bajtovima, pa su ponovo kalibrisani nad prenetim: 3 / 5 / 8 MB.
```

## 6. Zapažanja (odluke, ne defekti)

- **O-5, i dalje otvoreno: sajt koji ne odgovara nema nalaz.** Dva domena ne odgovaraju i `failed`
  su bez nalaza, a šest bez DNS zapisa ima `critical`. Oba znače da se sajt ne otvara. Predlog za v2
  ostaje isti: nalaz `infra.unreachable`.
- **O-7: od čega se sastoji `partial` od 14,4 %.** Budžet je potrošen kod 4 domena (4,4 %). Ostalo su
  iskreni `unknown`: kod 5 sajtova uzorak ima manje od 3 stranice (4 sajta pokazuju samo 1–2
  stranice, a kod jednog je budžet istekao posle početne), pa provere duplikata nemaju šta da uporede;
  kod 3 sajta slike se učitavaju tek pri skrolovanju; kod 3 tekst crta JavaScript, pa ga u sirovom
  HTML-u nema dovoljno za prepoznavanje jezika; kod 2 sonde za lažni 404 nisu dale odgovor iz kog bi
  se nešto zaključilo; kod 1 sertifikat nije proveren. Neki domeni imaju više razloga. Kriterijum od
  10 % pisan je pre odluke da se lažni nalazi pretvore u `unknown`, i ta odluka ga je podigla.
  Predlog: (a) na sajtu koji ukupno pokazuje manje od 3 stranice provere duplikata daju „ne
  primenjuje se", a ne `unknown`, što dva domena prebacuje u `scanned` (12,2 %); (b) kriterijum podeliti na
  `partial` zbog budžeta < 10 % (sada 4,4 %) i `unknown` po proveri < 20 %.
- **O-8: domeni bez DNS-a u vrhu liste.** Šest takvih domena stoji između 8. i 13. mesta, jer je
  `infra.dns.unresolved` `critical`. Ugašen sajt može biti lead, ali može biti i ugašen posao.
  Predlog za v2: posebna lista „ne rade" pored rangiranja.
- **O-9: `seo.canonical.duplicate` broji i početnu stranu.** Na sajtu na prvom mestu dve podstranice
  prijavljuju početnu kao zvaničnu adresu, pa ih Google može izostaviti iz pretrage. To je provereno
  curl-om i tačno je. Ali treća stranica u pravilu „≥ 3 stranice" je sama početna, koja legitimno
  upućuje na sebe. Tako dve podstranice od sedam daju `critical` i prvo mesto. Predlog: brojati samo
  stranice kojima canonical nije njihova sopstvena adresa.
- **O-10: stranica koja učitava i posle `load`.** Isti sajt je u dva prolaza napravio 179, pa 281
  zahtev. Posle BUG-016 razlika u težini je manja, ali broj zahteva i težina i dalje zavise od toga
  koliko dugo merenje traje.
- **O-11: HTML izveštaj prikazuje decimalnu tačku** („99.4"), a rečenice za klijenta zarez.
- **O-12: `optional` u registru ne koristi nijedna provera.** Rezervisan je za planiranu proveru
  kanonizacije hosta.
- **O-13: ispravka IT-SKENER-001, O-2.** Primer „isti sajt jednom 8,5, drugi put 26,9 MB" naveden je
  kao dokaz da video menja težinu, ali taj sajt nema nijedan video bajt. Razliku su pravile skripte i
  stilovi (O-10) i raspakovani bajtovi (BUG-016). Odluka da video ne ulazi u prag i dalje stoji: drugi
  sajt je u jednom prolazu preneo 77 MB videa, a u drugom 39 MB.

Posle nove kalibracije težina je vodeći nalaz kod 12 domena i kod 8 od prvih 20. U A je bila vodeći
nalaz kod 15 od prvih 20, sa pragom koji je palio skoro svima.

## 7. Zaključak i preporuka

Alat je stabilan: tri prolaza nad 100 domena bez ijednog pada i bez ijedne greške u logu. Posle ovog
ciklusa je i tačniji. Svi poznati lažni nalazi su ispravljeni i potvrđeni na pravim sajtovima, a
brojevi koji idu klijentu (vreme učitavanja, težina) sada se mogu ponoviti van alata.

Jedini neispunjen izlazni kriterijum je `partial` od 14,4 %. On ne dolazi od kvara: zbog budžeta je
4,4 %, a ostalo su mesta gde alat kaže „ne znam" i navodi razlog.

**Preporuka: prelazak na v2 je opravdan kad vlasnik proizvoda odluči o kriterijumu za `partial`
(O-7) i ručno pregleda prvih 5 u rangiranju.** O-5, O-7a, O-8 i O-9 su kandidati za plan v2.

## 8. Naučene lekcije

- Broj koji ide klijentu treba proveriti van alata i posle ispravke. BUG-016 se pokazao tek kad je
  ponovljeno merenje otkrilo da težina bez videa i dalje skače, a objašnjenje iz prethodnog izveštaja
  (video) zvučalo je uverljivo i bilo je pogrešno.
- mutmut 3 ne vidi kod koji radi pri importu. Takvi preživeli mutanti se proveravaju ručno, inače
  izveštaj ili potceni ili preceni testove.
- Pravilo „ono što se ne zna je `unknown`" i kriterijum „`partial` < 10 %" se sudaraju. Izlazni
  kriterijum treba pisati posle odluke o tome kako alat treba da se ponaša, ne pre nje.
