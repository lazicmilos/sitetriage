# Kalibracija

Dnevnik odluka iz provera na pravim sajtovima. Oblik: **zapažanje — uzrok — odluka**.
Kako se provera radi, piše u [`provera-na-pravim-sajtovima.md`](../real-site-verification.md).

## 2026-10-06 — novi pun prolaz nad listom B posle BUG-021 do BUG-026

BUG-022 menja nivo 1, pa je ponovljen ceo prolaz, sa kodom `d0e13a7`. Brze veze nije bilo, pa je
prolaz išao preko mobilnog hotspota, sa DNS-om 1.1.1.1 i `--concurrency 4` (nivo 1 sa 4 domena
odjednom umesto 16). Pre prolaza veza je bila 12,8–15,7 Mb/s, a Z-33 je pred nivo 2 izmerio
9,7 Mb/s. Nivo 1 je trajao 567 s. Pun nivo 2 je trajao 533 s za 60 sajtova, a lagani 139 s za 39,
sa dva konteksta. U logu nema WARNING ni ERROR.

- **Zapažanje:** 9,7 Mb/s je tik iznad granice od 9,6 (2 × profil). Ipak su sajtovi do `load`
  preuzimali brzinom od 3,8 Mb/s (medijana; p90 4,3), isto kao 5. 10. na 18,6 Mb/s. Medijana
  odnosa vremena učitavanja istih 56 sajtova je 1,03, a težine 1,00.
- **Uzrok:** usko grlo je i dalje bio profil od 4,8 Mb/s, a ne veza.
- **Odluka:** merenja vremena važe. Granica 2 × profil ostaje.

- **Kriterijumi iz §7 na B:**
  - nema padova;
  - `partial` zbog budžeta je 9,1 %;
  - `unknown` po proveri je najviše 5,1 %;
  - nijedan sajt koji ne radi nije u rangiranju;
  - statusi `scanned` / `partial` / `failed` / `unreachable` su 76 / 23 / 1 / 0.

  Jedan domen je `failed`, jer je na ulazu vratio 403 (zaštita od botova, poznata klasa „Nije
  skenirano"). Procena za 200 domena (36 min) ne važi za ovu vezu i 4 domena odjednom. Z-32 se meri
  na preporučenoj mašini.
- **BUG-022 na pravim sajtovima:** početna se promenila na tačno jednom sajtu: strani „uskoro", do
  koje se stiže preusmerenjem skriptom. Kod tog sajta su nestali nalazi o naslovu, opisu,
  canonical-u, og oznakama i jeziku. Nijedna druga početna se nije promenila.
- **BUG-021:** u ovom prolazu se nije pojavio. Nijedna strana na nivou 2 nije vratila status ≥ 400.
  Sa User-Agent-om „Chrome/" broj zahteva na sajtu sa reklamama je 115, a Chrome je izmerio 144.
  Sa „HeadlessChrome/" (5. 10.) bilo ih je 66.
- **Naslov, opis i canonical posle JavaScript-a (O-19):** nijedan od 99 sajtova ih ne postavlja
  samo JavaScript-om. Svih 13 nalaza `seo.description.missing` i svih 23 `seo.canonical.missing`
  ostaju i posle JS-a.
  - **Odluka (vlasnik):** `seo.*.missing` i dalje čita sirovi HTML. Polja `dom.*` ostaju u snimku.

- **Zapažanje:** sajt kome je težina tik uz prag od 7 MB pao je u rangiranju sa 4. na 35. mesto. Dana
  5. 10. dobio je lagani nivo 2: bez profila je do `load` preuzeo 8,6 MB i 116 zahteva. Sada je
  dobio pun nivo 2 i preuzeo 6,8 MB i 84 zahteva. Chrome pod profilom je 5. 10. izmerio 7,2 MB.
  Između 5. i 6. 10. način merenja su promenila 3 sajta. Na jednom je lagani nivo dao 26 % više, a
  na dva isto. Kod 38 sajtova koji su oba dana mereni lagano i 56 merenih punim nivoom medijana
  odnosa je 1,00.
- **Uzrok:** nije utvrđen. Za zaključak su 3 slučaja premalo.
- **Odluka:** ostaje zapažanje za sledeći ciklus. Pravilo od 80 % iz Z-52 ovaj slučaj pokriva.

- **Z-52, treći krug:**
  - u prvih 10 je 96 od 96 nalaza tačno: 59 provereno urllib-om, 37 skriptom u browseru;
  - „poslao bih": 7 od 10;
  - u poslednjih 5 nema promašenog ozbiljnog problema: najteža početna ima 1,9 MB, najduže
    učitavanje traje 5,5 s, i svih 5 radi na https-u.

  U prvih 10 je 9 istih sajtova kao 5. 10.
- **Zapažanje:** početna bez `<meta name="viewport">` se na telefonu prikazuje kao smanjena desktop
  strana, sa tekstom koji se ne može čitati. Alat to ne proverava. Kandidat je za novu proveru, uz
  „početnu skoro bez sadržaja".

## 2026-10-05 — ponovljen nivo 2 nad listom B: „delimično" i trajanje laganog nivoa 2

Nivo 1 je iz prolaza od 3. 10. (ispravke ga ne diraju). Nivo 2 je ponovljen 5. 10. sa BUG-019 i
BUG-020, preko mobilnog hotspota: Z-33 je izmerio 18,6 Mb/s. Pun nivo 2 je trajao 498 s za 60
sajtova, a lagani 168 s za 40 sajtova, sa tri konteksta odjednom. U logu nema WARNING ni ERROR.

- **Zapažanje:** `partial` je porastao sa 21 na 54 domena. Kod 29 od njih jedini uzrok je vreme
  učitavanja na laganom nivou 2.
- **Uzrok:** lagani nivo 2 vreme namerno ne meri, a alat je to beležio kao `unknown`
  (`requires.level2_full`). Svaki `unknown` čini domen `partial`.
- **Odluka (vlasnik):** vreme na laganom nivou 2 „ne primenjuje se" (`not_applicable`, isti
  razlog), pa domen zbog toga ostaje `scanned`. Provera kojoj preduslov nije ispunjen ne ulazi u
  imenilac udela `unknown`, jer nije ni pokrenuta.

- **Zapažanje:** formula iz prethodnog unosa daje premalu procenu za 200 domena. Pun nivo 2 ostaje
  na `max_level2` (60), pa na 200 domena lagani nivo 2 dobija oko 140 sajtova, a ne 2 × 40.
  Ispravno: 200 / n × nivo 1 + pun nivo 2 + (200 − punih) × vreme po laganom sajtu. Sa nivoom 1 sa
  brze veze (145 s) i ovim merenjem to je 290 + 498 + 140 × 4,2 ≈ 1376 s, oko 23 min, a granica je
  15 min.
- **Uzrok:** lagani nivo 2 radi sa istim brojem konteksta kao pun (`browser.concurrency` = 3). Pun
  nivo 2 svakako učitava jedan po jedan, a laganom brzinu određuje baš broj konteksta.
- **Odluka (vlasnik):** alat treba da radi na svakoj mašini, a da na jačoj bude brži. Lagani nivo 2
  bira broj konteksta po mašini: jedan na svaki slobodan GB memorije, najviše dva po jezgru i
  najviše 8 (`browser.light_concurrency = 0`; broj ≥ 1 ga fiksira). Granica od 15 min za 200
  domena (Z-32) važi za preporučenu mašinu: 16 GB RAM-a i veza od bar 50 Mb/s. Na slabijoj mašini
  prolaz traje duže. Procena za preporučenu mašinu još nije izmerena. Potvrđuje se prvim prolazom
  na takvoj mašini.

## 2026-10-04 — ručna provera liste B (Z-52): User-Agent nivoa 2 i strane bez nivoa 2

Ulaz je prolaz nad B od 3. 10. (veza 136,4 Mb/s) i merenje van alata 4. 10.: svoj Chromium sa
UA browsera, pod istim profilom (4,8 / 1,5 Mb/s, 150 ms), dva učitavanja po sajtu.

- **Zapažanje:** u prvih 10 dva nalaza na istom sajtu ne stoje. Alat je izmerio 2,7 MB i 129
  zahteva do `load` i 6,2 s, a browser 2,2 MB sa svim posle `load` i 4,4 s. Kod kuće, po hostu: sa
  UA alata 2,1–2,4 MB i 120–133 zahteva do `load`, sa UA browsera 1,2–1,3 MB i 58. Razliku prave
  reklame: više reklamnih mreža i više aukcija. Na drugom sajtu Google Fonts je UA alata slao
  fontove od 1315 kB, a browseru 657 kB. Ostalih 8 iz prvih 10 je u granici ±4 %.
- **Uzrok:** UA nivoa 2 bio je samo identitet operatera (`MlazicSiteScanner/…`). Servisi koji
  biraju sadržaj po UA takvom posetiocu šalju težu stranu nego browseru.
- **Odluka (vlasnik):** browser šalje UA koji Chromium sam prijavljuje, sa identitetom dopisanim na
  kraj (BUG-019). Izmereno: isto kao Chrome (1,31 MB, fontovi 657 kB), pa nije potrebno sakrivati
  da je browser automatizovan. Pragovi iz Z-50 ostaju. Kalibrisani su sa starim UA, a novi daje
  iste ili manje brojeve, pa prag može samo da da manje nalaza. Ponovo se proveravaju pri sledećem
  prolazu nad A.

- **Zapažanje:** od poslednjih 5 rangiranih dve strane imaju 4,8 i 4,9 MB (jedna i `load` preko
  9 s), a ostale tri 3,2 MB, do 107 zahteva i 3,4 MB. Nijedna nije bila na nivou 2, pa u
  izveštaju stoje sa „0 nalaza".
- **Uzrok:** nisu imale razlog za eskalaciju: HTML 89–148 kB, sažet, početna ispod 1,5 s, h1
  postoji, dovoljno teksta, nijedan nalaz ≥ medium. Broj slika, skripti i stilova u HTML-u ne
  razdvaja ih od lakih strana. Na B je bio 91 kandidat na 60 mesta, pa ni nov razlog za eskalaciju
  ne bi pomogao.
- **Odluka (vlasnik):** svaki sajt sa početnom koja radi, a bez mesta na punom nivou 2, dobija
  lagani nivo 2: posle punog, bez profila i bez reda za učitavanje (BUG-020). Vreme učitavanja je
  za njih `unknown` (`requires.level2_full`) i ne ulazi u kriterijum „`unknown` < 20 %": imenilac
  za vreme su sajtovi mereni pod profilom. Lagani nivo 2 raste sa brojem domena, pa je procena
  za 200 domena 200 / n × (nivo 1 + lagani nivo 2) + nivo 2. Meri se u ponovljenom prolazu nad B.

## 2026-09-28 — prolaz nad listom A sa GitHub Actions: sajtovi koji rade u „Ne rade”

Prolaz je pušten ručno iz `.github/workflows/prolaz.yml` (kod `a9cbabb`), jer kod kuće nema brze
veze za Z-51. Z-33 je izmerio 763 Mb/s, a u logu nema nijednog WARNING ni ERROR.

- **Zapažanje:** u „Ne rade” je 13 domena, a u prolazu H, dan ranije sa veze u Srbiji, bilo ih je 7.
  Svih 7 iz H su i ovde. Novih 6 ne prihvataju vezu ni na 443 ni na 80, u oba pokušaja. Pet od njih
  je kod istog hostinga u Srbiji, na susednim adresama. U prolazu H svih šest je skenirano, a
  28.09. sa kućne adrese pet od šest odgovara sa 200 ili 301.
- **Uzrok:** hosting odbacuje veze sa GitHub-ovih adresa (datacentar van Srbije). Za alat to
  izgleda isto kao ugašen server, pa sajt ide u „Ne rade”, sa nacrtom mejla koji vlasniku kaže da
  mu sajt ne radi. To je lažan nalaz.
- Ostalo se poklapa sa H: težina i broj zahteva do `load` su p50 2,1 MB i 56 (H 2,2 MB i 57),
  vreme do `load` je p50 / p90
  5,7 / 16,9 s (H 5,6 / 15,2 s), a prekida je 4. Trajanje nivoa 2 po domenu (`elapsed_ms`) je ovde
  izmereno prvi put: p50 8,8 s, p95 26,6 s, najviše 31,4 s, dakle daleko ispod granice od 60 s.
- **Odluka:** prolaz sa GitHub-a ne važi za Z-51, jer lista „Ne rade” ima poznate lažne unose.
  Prolaz nad B ide sa adrese u Srbiji. Za web fazu je ovo rizik: server van Srbije ili u
  datacentru dobija isti odgovor od istih hostinga.

## 2026-09-28 — Z-50: pragovi težine, broja zahteva i vremena, i canonical na listi A

Ulaz je prolaz H (lista A, 100 domena, kod `3607cb7`, brza veza; Z-33 je izmerio 107 Mb/s), po
odluci vlasnika, bez novog skeniranja. Raspodelu daje `scripts/raspodela.py`. Do `load` je stiglo
58 sajtova. Pod profilom je mereno 60, od toga su 2 prekida, računata kao 25 s.

| | p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|---|
| težina do `load` bez videa | 2,2 MB | 3,6 MB | 7,3 MB | 8,7 MB | 13,4 MB |
| zahteva do `load` | 57 | 87 | 130 | 185 | 310 |
| vreme do `load` pod profilom | 5,6 s | 9,3 s | 15,2 s | 22,1 s | ≥ 25 s |

- **Zapažanje:** pragovi 3 / 5 / 8 MB i 100 / 150 zahteva kalibrisani su u v1, na ukupnim
  vrednostima, sa onim što stigne posle `load`. Pragovi 4 / 8 s određeni su na stvarnoj vezi. Pod
  profilom je `perf.load.time` imao nalaz kod 42 od 60 sajtova.
- **Uzrok:** posle Z-24 se broji samo do `load`, pa su težina i broj zahteva manji. Posle Z-30 se
  vreme meri na sporijoj simuliranoj vezi, pa je duže.
- **Odluka (vlasnik, 28.09.):** pragovi su zaokruženi p50, p75 i p90, isti postupak kao u v1. Kod
  provera sa dva nivoa isti percentil daje istu ozbiljnost kao kod težine: p50 medium, p75 high.

| Prag | Bilo | Sada | Nalaza u prolazu H, pre → posle |
|---|---|---|---|
| težina (medium / high / critical) | 3 / 5 / 8 MB | 2 / 4 / 7 MB | 20 → 32 |
| zahteva (medium / high) | 100 / 150 | 60 / 90 | 11 → 28 |
| vreme (medium / high) | 4 / 8 s | 6 / 9 s | 42 → 25 |

- `browser.timeout_s` ostaje 25 s: p95 je 22,1 s, pa je rezerva oko 3 s.
- `browser.max_seconds_per_domain` ostaje 60 s (vlasnik, 28.09.). Trajanje nivoa 2 po domenu nije
  bilo u snimcima, a log ga ne daje tačno, jer „nivo 2 počinje" stoji pre čekanja u redu za
  učitavanje. Od sada je u snimku (`elapsed_ms`), a prvi put se meri na listi B. U prolazima F, G
  i H nijedan domen nije dostigao granicu.
- Mrežni profil ostaje 4,8 / 1,5 Mb/s i 150 ms. Kašnjenje od 150 ms je isto koje Lighthouse koristi
  za mobilno merenje. Pri učitavanju stranica šalje uglavnom kratke zahteve, pa se odlazni protok
  ne kalibriše.
- Posle `recheck`-a sa novim pragovima prvih 10 u rangiranju su isti sajtovi kao u prolazu H.
  Jedan se popeo sa 8. na 1. mesto, jer mu je težina sada `critical`.

### canonical

- **Zapažanje:** na listi A su 2 nalaza `seo.canonical.duplicate`, oba medium, sa udelom 0,25
  (2 od 8 stranica). Kod prvog dve podstranice, „o nama” i kategorija proizvoda, prijavljuju
  početnu kao zvaničnu adresu, pa ih Google može izostaviti iz pretrage. To je stvaran problem.
  Kod drugog početna na `https://` ima canonical na svoju `http://` verziju, a jedna podstranica
  ispravno upućuje na početnu. Sve četiri stranice su 28.09. proverene `curl`-om, i canonical je
  isti kao u snimku.
- **Uzrok:** poređenje je `http`/`https` i vodeće `www.` iste stranice računalo kao drugu adresu, pa
  bi rečenica vlasniku kao „drugu adresu” pokazala njegovu sopstvenu početnu.
- **Odluka (vlasnik, 28.09.):** canonical koji se od stranice razlikuje samo po `http`/`https` ili po
  vodećem `www.` ne računa se kao tuđi, pa drugi nalaz nestaje. Granice udela (0,4 high, 0,6
  critical) ostaju početne. Na A je samo jedan stvaran slučaj, i on sa udelom 0,25 dobija medium.

## 2026-09-28 — prolazi G i H: Z-32, Z-31 i Z-24 sa brze veze

Oba prolaza su 27.09. rađena nad listom A, sa istim kodom (`3607cb7`: 16 domena odjednom na nivou
1, privremena greška DNS-a se ponavlja jednom). Prolaz G je rađen preko mobilnog hotspota, a prolaz
H na drugom računaru, sa brze veze. Z-33 je pre nivoa 2 izmerio 17,4 Mb/s (G) i 107 Mb/s (H).

| | G (hotspot) | H (brza veza) |
|---|---|---|
| nivo 1 | 192 s | 168 s |
| nivo 2 (60 domena) | 763 s | 500 s |
| procena za 200 domena | 19,1 min | 13,9 min |
| udeo potrošenog budžeta | 20,5 % | 7,8 % |
| `failed` zbog privremene greške DNS-a | 7 | 0 |
| do `load` pod profilom: medijana / p90 | 7,5 / 21,8 s | 5,5 / 14,1 s |
| rok od 25 s istekao | 9 | 2 |

U oba prolaza „Ne rade” ima istih 7 domena kao u prolazu D. U prolazu H su `failed` samo 3 sajta sa
odgovorom 403 ili 429, kao u prolazu D.

- **Zapažanje (Z-32):** na brzoj vezi procena je 2 × 168 s + 500 s = 13,9 min, ispod granice od
  15 min, i to uz učitavanje jedan po jedan. Na hotspotu je 19,1 min. U oba prolaza najveći deo
  vremena odnosi nivo 2, jer se 60 sajtova učitava jedan po jedan pod profilom od 4,8 Mb/s.
- **Uzrok (G):** na hotspotu 16 domena odjednom dele vezu od oko 17 Mb/s, pa su sajtovi sporiji i
  više njih potroši budžet. Privremena greška DNS-a posle ponavljanja ostala je kod 7 domena (F: 24).
  Na brzoj vezi se ne javlja ni jedno ni drugo.
- **Zapažanje (Z-31, ponovljeno sa brze veze):** isti postupak i istih 10 sajtova kao 27.09.
  Stvarna veza pre četiri prolaza: 280, 358, 280 i 360 Mb/s (preuzimanje 25 MB). Odnos „u prolazu /
  sam” je u opsegu 0,8–1,25 kod 19 od 20 merenja, a kod 15 je između 0,97 i 1,03. Jedino odstupanje
  je 0,77: taj sajt se sam učitao za 5,2 s, a u ostala tri merenja za 4,0–4,1 s. Razlika je na
  strani sajta, jer ometanje daje odnos veći od 1. Nivo 2 za 10 sajtova traje 41,5 s uporedo, a
  93–95 s jedan po jedan.
- **Z-24, sa brze veze:** kad se sajtovi mere sami, težina i broj zahteva do `load` su u granici od
  10 % kod 10 od 10 sajtova. Najveća razlika je 5,7 % broja zahteva. Uslov „bar 9 od 10” je sada
  ispunjen i formalno.
- **Odluka (vlasnik, 28.09.):** Z-32 je ispunjen. 16 domena odjednom ostaje, jer je udeo potrošenog
  budžeta na brzoj vezi 7,8 % (kriterijum < 10 %), a `max_level2` ostaje 60. `browser.serial_load`
  ostaje `true`, jer uslov iz Z-31 traži svih 20 merenja, a Z-32 je ispunjen i bez uporednog
  učitavanja. Veza mašine na kojoj skener radi nije unapred poznata. Jedan po jedan daje tačno
  vreme na svakoj vezi od 9,6 Mb/s naviše (Z-33), a uporedno je provereno samo na vezi od oko
  100 Mb/s i više. Automatski izbor prema izmerenoj vezi tražio bi merenja između 17 i 107 Mb/s, pa
  ostaje za kasnije. Ako se uporedno učitavanje ikad uključi, `min_link_ratio` mora biti bar 3, jer
  se tada tri sajta učitavaju odjednom.
- **Otvoreno:** na hotspotu procena prelazi 15 min, pa i dalje ostaje pitanje gde se rade pravi
  prolazi. Z-32, Z-50 i Z-51 važe za brzu vezu.

## 2026-09-27 — prolaz F: vreme pod profilom, DNS preko hotspota i Z-32

Lista A, 100 domena, 14,6 min. Računar je bio na mobilnom hotspotu, preko Wi-Fi adaptera 802.11g
(oko 17 Mb/s). Z-33 je pre nivoa 2 izmerio stvarnu vezu od 15,6 Mb/s, što je iznad potrebnih
9,6 Mb/s, pa je vreme mereno pod profilom.

- **Zapažanje:** 24 od 100 domena su `failed` zbog privremene greške DNS-a (EAI_AGAIN). Greške su
  raspoređene kroz ceo nivo 1, a svi ti sajtovi su u prolazu E radili. Pod profilom je 55 sajtova
  stiglo do `load`: medijana 6,5 s, p75 9,8 s, p90 13,9 s. Kod 4 sajta rok od 25 s je istekao.
  `perf.load.time` ima nalaz kod 50 od 55 sajtova (27 medium, 23 high); u prolazu E, bez profila,
  bilo je 40 nalaza.
- **Uzrok:** DNS preko hotspota povremeno ne odgovori, a alat privremenu grešku DNS-a nije
  ponavljao. Pragovi za vreme (4 i 8 s) određeni su na stvarnoj vezi, pa pod profilom pale skoro
  svima.
- **Z-32:** procena za 200 domena je 2 × 322 s (nivo 1, prolaz E, kad su svi domeni radili) plus
  587 s (nivo 2, prolaz F, 59 domena), oko 20,5 min, a granica je 15 min. Nivo 1 sam troši oko
  10,7 min, pa bi samo spuštanjem `max_level2` nivo 2 smeo da ima oko 25 domena umesto 60.
- **Odluka (vlasnik, 27.09.):** privremena greška DNS-a se ponavlja jednom, na nivou 1 i u proveri
  adresa na nivou 2. Nivo 1 obrađuje 16 domena odjednom umesto 8 (`http.domain_concurrency`,
  `http.concurrency`), jer uglavnom čeka pauze ka istom sajtu. Ovo je odstupanje od Z-32, koji
  predviđa spuštanje `max_level2`. Pristojnost prema svakom sajtu se ne menja. Z-32 se meri
  sledećim prolazom nad listom A. Pragovi za vreme ostaju do Z-50.

## 2026-09-27 — Z-31: učitavanje uporedo pod profilom, i ponovljeno merenje Z-24

Merenje je rađeno nad 10 sajtova sa liste A, raspoređenih po vremenu učitavanja iz prolaza E. Svi
su teški do 3,6 MB i nemaju video. Prolazi su bili četiri, svi sa `--level 2`, pod profilom:
uporedo (`serial_load = false`, 3 konteksta), sam (`browser.concurrency = 1`), sam, pa ponovo
uporedo. Pre svakog prolaza izmerena je stvarna veza, preuzimanjem 25 MB: 3,2, 3,3, 4,5 i 1,9 Mb/s.

- **Zapažanje (Z-31):** odnos „u prolazu / sam” bio je od 0,44 do 3,68. U opsegu 0,8–1,25 bio je 1
  od 8 uporedivih sajtova u prvom ponavljanju i 3 od 9 u drugom. Ni vreme istog sajta merenog samog
  se nije ponovilo: jedan sajt od 1,7 MB učitao se jednom za 4,7 s, a drugi put za 20,4 s. Dva
  sajta u pojedinim prolazima nisu stigla do `load` za 25 s.
- **Uzrok:** stvarna veza je u svakom merenju bila sporija od profila (4,8 Mb/s), a profil može samo
  da uspori. Vreme je zato mereno brzinom stvarne veze, koja se menjala iz minuta u minut, a sajtovi
  koji se učitavaju uporedo dele tu vezu. Pod profilom bi taj sajt od 1,7 MB trebalo da se učita za
  oko 3–5 s, koliko je dao prvi put.
- **Odluka:** `browser.serial_load` ostaje `true`, jer uslov iz Z-31 nije ispunjen. Eksperiment ne
  odgovara na pitanje iz Z-31, da li je stvarna veza znatno brža od 3 × 4,8 Mb/s, jer veza nije bila
  brža ni od jedne. Ako paralelno učitavanje zatreba za Z-32, eksperiment se ponavlja sa veze od
  najmanje 15 Mb/s.
- **Z-24, ponovljeno posle Z-30:** kad se sajtovi mere sami, težina i broj zahteva do `load` su u
  granici od 10 % kod 8 od 8 uporedivih sajtova. Najveća razlika je 8,7 % težine. Dva sajta nisu
  uporediva, jer u jednom od prolaza nisu stigla do `load`. U prolazima uporedo 7 od 9 je u
  granici, a dva su preko (37 % i 13 %), ali taj način se ne koristi u radu. Uslov „bar 9 od 10”
  formalno nije ispunjen, zbog dva sajta kojima je rok istekao na sporoj vezi.
- **Odluke vlasnika (27.09.):** Z-24 je priznat na osnovu rezultata 8 od 8, a na listi B (Z-51) se
  ponovo vidi sa brze veze. Dodat je Z-33: pre nivoa 2 alat meri stvarnu vezu, a kad je sporija od
  `min_link_ratio` × profil (početno 2 × 4,8 = 9,6 Mb/s), vreme učitavanja je `unknown`.
- **Otvoreno:** gde se rade pravi prolazi. Kalibracija vremena (Z-50) i lista B (Z-51) traže vezu
  od najmanje 15 Mb/s.

## 2026-09-27 — mrežni profil nivoa 2 (Z-30)

- **Zapažanje:** vreme učitavanja zavisilo je od veze sa koje se meri, a rečenice su računale sa
  4,8 Mb/s. Na lokalnom serveru stranica sa 600 kB skripte bez profila se učita za oko 60 ms, a
  pod profilom za oko 1,4 s. Pun Chromium iframe sa drugog sajta učitava u poseban proces, i taj
  iframe profil nije usporavao (274 ms prema 1397 ms).
- **Uzrok:** mreža se nije simulirala, a profil postavljen na stranicu ne važi za poseban proces
  iframe-a.
- **Odluka:** nivo 2 meri pod `[network_profile]` (4,8 / 1,5 Mb/s, 150 ms), a Chromium radi bez
  izolacije sajtova ([ADR-010](../adr/ADR-010-mrezni-profil.md)). Pragovi `load_ms` (4 / 8 s),
  `browser.timeout_s` (25 s) i `browser.max_seconds_per_domain` (60 s) ostaju do Z-50, kad se
  određuju iz raspodele izmerene pod profilom. Do tada očekuj više nalaza za vreme. Na 0,6 MB/s
  medijana prenete težine sa liste A (oko 3 MB) traje oko 5 s, a p90 (oko 8 MB) oko 13 s, pa
  prag od 4 s prelazi većina sajtova.

## 2026-09-27 — prolaz E: Z-26 posle popravke varijanti

Lista A, 100 domena, 15,3 min, bez upozorenja i grešaka u logu. Udeo domena sa potrošenim
budžetom je 8,9 % (kriterijum < 10 %). Medijana vremena po domenu je 22,6 s (prolaz C 15,7 s,
prolaz D 28,1 s), a u uzorku je ukupno 635 stranica (C 640, D 592).

- **Zapažanje:** 9 domena je potrošilo budžet, a dozvoljeno je 8 (prolaz C 6).
- **Uzrok:** 4 domena su potrošila budžet i u prolazu C. Jedan sajt je tog dana vraćao 500 na mapu
  sajta, sonde i 4 od 7 stranica. Svaki 500 se ponavlja jednom, pa je taj domen potrošio svih 19
  zahteva za 19 s, a ne vreme. Preostala 4 su spori sajtovi, sa oko 3 s po stranici, koji su i u
  prolazu C trošili 35–43 s od 40. Tri zahteva za varijante, svaki sa pauzom pristojnosti, guraju
  ih preko granice. To je cena koju predviđa rizik R-2. Ti sajtovi su ipak dobili 3–7 stranica.
- **Odluka (vlasnik, 27.09.):** Z-26 je ispunjen. Jedini domen preko granice je onaj sa greškama
  500 na strani sajta, udeo budžeta je ispod izlaznog kriterijuma, a uzrok iz prolaza D je
  popravljen. Budžet ostaje 19 zahteva i 40 s.

## 2026-09-27 — prolaz D: prihvatanje F2 (Z-20, Z-21, Z-25, Z-26)

Lista A, 100 domena, 16,8 min, bez upozorenja i grešaka u logu. Najveći udeo `unknown` po proveri
je 15 % (kriterijum < 20 %). Udeo domena sa potrošenim budžetom je 22 % (kriterijum < 10 %).

### Z-20: ispunjeno

- **Zapažanje:** 7 domena je u „Ne rade”, 6 zbog DNS-a i 1 bez odgovora. Svih 7 je potvrđeno van
  alata, DNS upitom i `curl`-om na https i http. U „Nije skenirano” su 3 sajta sa odgovorom 403 ili
  429, a ne u „Ne rade”. Kod dva od njih `curl` dobija 200, a alat 403: to je zaštita od botova.
  Svaki rangiran domen je dobio HTTP odgovor.
- **Odluka:** uslov je ispunjen.

### Z-26: nije ispunjeno, popravljen uzrok

- **Zapažanje:** 21 domen je potrošio budžet, a u prolazu C 6 (dozvoljeno je 8). Kod 19 od njih
  isteklo je 40 s, a potrošeno je 7–17 od 19 zahteva. Varijante idu pre uzorka, pa je uzorku
  ostalo malo vremena: neki domeni su imali 1 stranicu umesto 8.
- **Uzrok:** varijanta je pratila preusmerenje do kraja. Na tim domenima 57 od 63 varijante
  završava na početnoj koja je već preuzeta, pa se početna preuzimala još tri puta. Na sporom
  hostingu to je 3–10 s po preuzimanju. Sporedni uzrok: sajtovi su tog dana odgovarali sporije.
  Medijana početne je bila 1,8 s, a u prolazu C 0,8 s.
- **Odluka (vlasnik, 27.09.):** popravlja se uzrok, a ne budžet. Varijanta prati preusmerenje
  korak po korak i staje pred početnom, a status i canonical uzima od nje. U prolazu D 207
  varijanti završava na početnoj, i kod svih su status i canonical isti kao kod početne, pa se
  nalazi ne menjaju. Budžet ostaje 19 zahteva i 40 s. Uslov se meri ponovo u sledećem prolazu nad
  listom A. Testovi: `test_preusmerenje_na_vec_preuzetu_adresu_se_ne_prati`,
  `test_varijanta_koja_vodi_na_pocetnu_je_ne_trazi_ponovo`.

### Z-25 i Z-21: ispunjeno po tumačenju vlasnika

- **Zapažanje:** sva 3 sajta iz O-7 prošla su nivo 2, ali i posle JS-a imaju 12, 242 i 56
  znakova teksta, a prag je 400. To su strana sa jednim dugmetom, strana „u pripremi” i strana
  koja ima samo podnožje. `i18n.lang.mismatch` je zato `unknown` (`text_too_short_rendered`), a
  `missing` i `invalid` rade nad renderovanim stanjem. Od 5 sajtova koji su u prolazu C imali manje
  od 3 stranice, 1 je dopunom vezama došao do 7 stranica i prešao u `scanned`. Tri zaista imaju
  1–2 stranice, pa su im provere duplikata `not_applicable`, ali ostaju `partial` zbog kratkog
  teksta ili neproverene varijante hosta. Peti je ostao bez budžeta i ostaje `partial`, kako Z-21
  traži.
- **Uzrok:** pretpostavka iz O-7 da tekst crta JS nije tačna. Teksta nema ni u pregledaču.
- **Odluka (vlasnik, 27.09.):** `unknown` sa razlogom je ovde tačan odgovor, a `ok` ili nalaz
  bili bi nagađanje. Uslovi Z-25 i Z-21 se smatraju ispunjenim. `partial` koji dolazi od drugih
  provera nije predmet Z-21.

## 2026-09-26 — kanonizacija hosta i budžet od 19 zahteva (Z-26)

- **Zapažanje:** u IT-SKENER-002 (O-12) `optional` u registru nije koristila nijedna provera. Čekao
  je kanonizaciju hosta, a sajt koji se otvara na više adresa bez preusmerenja čest je i proverljiv
  problem malih sajtova.
- **Uzrok:** provera je bila planirana za v1, ali nije urađena.
- **Odluka:** posle `robots.txt`, a pre mape sajta, idu tri zahteva za preostale adrese konačnog
  porekla, pa je budžet 19 zahteva umesto 16. `infra.host.duplicate` gleda samo hostove (`www` i
  bez `www`). Sajt koji radi i na `http://` i na `https://` istog hosta prijavljuje samo
  `infra.https.redirect.missing`, da jedan problem ne da dva nalaza (odluka vlasnika, 26.09.).
  Prihvatanje: na listi A broj domena sa potrošenim budžetom ne raste za više od 2 u odnosu na
  prolaz C (6). Meri se u prvom sledećem prolazu nad listom A.

## 2026-09-26 — težina i broj zahteva do događaja `load` (Z-24)

- **Zapažanje:** u IT-SKENER-002 (O-10) isti sajt je u dva prolaza imao 179, pa 281 zahtev (+57 %).
- **Uzrok:** brojač je sabirao sve do kraja mirovanja mreže, skrola i čekanja na tela, a posle
  `load` stižu analitika, chat i lenje slike, koliko ih vreme merenja uhvati.
- **Odluka:** prag i rečenica za klijenta gledaju samo zahteve započete pre `load`, a telo takvog
  zahteva se broji i kad stigne posle njega. Pragovi 3 / 5 / 8 MB i 100 / 150 zahteva ostaju, iako
  su kalibrisani na ukupnim vrednostima; nova raspodela se meri u Z-50. Prihvatanje: deset sajtova
  sa liste A, po dva merenja, razlika ≤ 10 % kod bar 9 od 10.

### Prihvatanje, prvo merenje (dva para, bez mrežnog profila)

Deset sajtova sa liste A, raspoređenih po težini od 0,6 do 22 MB, izmereno je u dva para, po dva
prolaza sa `--level 2`.

| Par | Stiglo do `load` u oba prolaza | Razlika ≤ 10 % | Ne poredi se |
|---|---|---|---|
| 1 | 7 od 10 | 6 od 7 | 3: rok od 25 s istekao (jedan sajt u oba prolaza, dva samo u drugom) |
| 2 | 6 od 10 | 5 od 6 | 4: rok istekao (2), nivo 2 pao na DNS-u (2) |

- **Zapažanje:** kod sajtova koji su u oba prolaza stigli do `load`, težina i broj zahteva do
  `load` razlikuju se ≤ 1 %, osim jednog sajta. Ukupan broj zahteva istog sajta menjao se sa 107 na
  86, a do `load` je u sva četiri prolaza bio 8. Taj jedan sajt je odstupao 13 % i 17 %, i to
  sistematski: prvi prolaz u paru imao je 124 zahteva i 2,11 MB slika do `load`, drugi 125–126
  zahteva i 2,65 MB, a ukupno slika bilo je svaki put oko 2,7 MB. Vreme do `load` istog sajta
  menjalo se i četvorostruko (4,8 s pa 17,9 s), a rok je ističao i sajtovima koji su u drugom
  prolazu stigli do `load` za 7 s.
- **Uzrok:** prvi prolaz u paru dolazio je posle desetak minuta pauze, a drugi dva-tri minuta
  kasnije. Najverovatnije server ili CDN sajta brže odgovara kad je „zagrejan", pa jedna slika od
  oko 540 kB krene pre `load`. To je ponašanje sajta tik uz granicu `load`, a ne šum koji pravilo
  može da ukloni. Sajtovi koji se ne porede otpali su zbog brzine veze u trenutku merenja i zbog
  neuspelog DNS upita. SSRF zaštita nivoa 2 tada blokira zahtev, pa Chromium javlja
  `ERR_BLOCKED_BY_CLIENT`, iako adresa nije privatna.
- **Odluka:** kod za Z-24 ostaje. Merenje se ponavlja posle Z-30, pod fiksnim mrežnim profilom, i
  tada se rok nivoa 2 posmatra zajedno sa Z-50.

### Zahtev tik pre `load` ume da se broji posle njega

- **Zapažanje:** test za Z-24 pao je u CI-ju (`cda6b0f`). `fetch` koji skripta pošalje pre `load`
  brojao se kao da je krenuo posle njega. Lokalno, pod opterećenjem procesora, to se desilo 3 puta u
  15 ponavljanja.
- **Uzrok:** nivo 2 presreće svaki zahtev (SSRF zaštita), a Playwright tada javlja zahtev tek kad
  stigne do mrežnog sloja, a ne kad ga stranica pošalje. Zahtev koji ne zadržava `load` (`fetch`
  ili XHR) i koji krene u poslednjim milisekundama pre `load` zato ponekad
  bude viđen posle `load`. Isto važi i za prave sajtove, ne samo za test.
- **Odluka:** za sada se ne popravlja. Greška pomera težinu i broj zahteva naniže, pa ne pravi lažne
  nalaze. Ne zna se da li je ona uzrok odstupanja od 13 % i 17 % iz prvog merenja. Ako merenje
  posle Z-30 opet pokaže odstupanje tik uz `load`, ovo je prvi kandidat.

## 2026-09-26 — `seo.canonical.duplicate` broji samo tuđi canonical (Z-23)

- **Zapažanje:** u IT-SKENER-002 (O-9) dve podstranice od sedam, koje upućuju na početnu, dale su
  `critical` i prvo mesto u rangiranju. Treća stranica u pravilu „≥ 3" bila je sama početna, a ona
  sa canonical-om na sebe je ispravna.
- **Uzrok:** pravilo je brojalo svaku stranicu sa istim canonical-om, i onu koja upućuje na sebe, a
  ozbiljnost je uvek bila `critical`, bez obzira na to koliki deo sajta je pogođen.
- **Odluka:** broje se samo stranice čiji canonical upućuje na drugu adresu
  (`canonical_foreign_min = 2`, iz bar dve grupe putanja, da paginacija jednog bloga ne bude
  nalaz). Ozbiljnost po udelu u uzorku: `canonical_share = { high = 0.4, critical = 0.6 }`, ispod
  toga `medium`. To su početne vrednosti iz specifikacije; granice se biraju u Z-50, posle
  `recheck`-a nad snapshotima liste A i provere svakog nalaza `curl`-om.

## 2026-09-24 — treći prolaz: težina iz prenetih bajtova

Ceo izveštaj: [`izvestaj-testiranja-2.md`](izvestaj-testiranja-2.md).

| Prag ili pravilo | Zapažanje | Odluka |
|---|---|---|
| šta se broji u težini | brojač je sabirao raspakovano telo; isti sajt: 25,3 MB raspakovano, 3,8 MB preneto (BUG-016) | broje se preneti bajtovi (`responseBodySize`) |
| `perf.page.weight` | preneto bez videa, 60 sajtova: medijana 2,8 MB, p75 5,2, p90 8,1, najviše 22,1 | 3 / 5 / 8 MB; zamenjuje 5 / 10 / 20 MB iz reda ispod |
| ispravka primera za video | „8,5 MB jednom, 26,9 MB drugi put" nije bio video: taj sajt nema nijedan video bajt, razliku prave skripte i stilovi koji se učitavaju i posle `load` | odluka o videu ostaje; pravi primer je sajt koji je u jednom prolazu preneo 77 MB videa, a u drugom 39 MB |

## 2026-09-24 — odluke posle prolaza nad 100 domena

| Prag ili pravilo | Zapažanje | Odluka |
|---|---|---|
| `perf.page.weight` | 55 od 60 sajtova preko 1,5 MB; medijana 4,4 MB, p75 10,6, p90 17,2 (raspakovani bajtovi) | 5 / 10 / 20 MB, bez videa (zamenjeno, vidi gore) |
| video u težini | isti sajt: 8,5 MB jednom, 26,9 MB drugi put (pogrešan primer, vidi ispravku gore) | ne ulazi u prag; u rečenici stoji posebno |
| vreme učitavanja | u prolazu do 4,6× duže nego kad se sajt meri sam | učitava se jedan po jedan; ostatak merenja paralelno |
| `http.max_seconds_per_domain` | 19 domena potrošilo 25 s; strana na sporom hostingu 1–3 s | 40 s; broj zahteva ostaje 16 |
| izbor za nivo 2 | 9 od 18 odsečenih kandidata bez ijednog nalaza nivoa 1 | prvo kandidati bez jakog nalaza nivoa 1 |
| `i18n.lang.mismatch` | tačan 28 od 28, ali poruka je tvrdila nešto o Google-u što nije tačno | poruka o čitačima ekrana; high → medium |
| `perf.compression.missing` | poruka je tvrdila „sekunda i po"; stvarna ušteda je desetinke sekunde | ušteda se računa iz veličine; medium → low |
| statusi 401/403/429/5xx | sajt iza zaštite od botova dobijao nalaze o robots.txt i mapi sajta | samo 404 i 410 znače „ne postoji"; ostalo je `unknown` |

## 2026-09-24 — prolaz nad 100 pravih domena

Ceo izveštaj: [`izvestaj-testiranja-100.md`](izvestaj-testiranja-100.md). Ukratko: 0 padova i 7,7 min
za 100 domena, ali `partial` 30 %, četiri otvorena defekta (BUG-003 do BUG-006) i šest zapažanja
(O-1 do O-6) koja čekaju odluku. Najvažnije među njima: prag težine stranice pali na 55 od 60 sajtova,
a vreme učitavanja je naduvano jer se meri dok tri sajta dele vezu.

## 2026-09-24 — prvi prolaz nad ispitnim skupom (8 domena)

Rezultat: 11/12 live testova, `partial` 3/8 (38 %), `unknown` za `infra.soft404` 25 %.

### institucija.example je popravljen

- **Zapažanje:** nema `seo.canonical.duplicate` ni `infra.soft404`, koje specifikacija očekuje.
- **Uzrok:** sajt je popravljen. Svih 8 stranica u uzorku ima sopstveni canonical, a obe sonde vraćaju 404.
- **Odluka:** alat radi ispravno. Oba nalaza su tada upisana kao popravljena u `tests/test_live.py` (lista je kasnije premeštena u `SKENER_LIVE_CSV`); fixture-i ostaju kao u specifikaciji.

### Velika mapa sajta pojede budžet pre sondi za lažni 404 (bag)

- **Zapažanje:** b2b-firma.example (6 mapa) i prodavnica.example (9 mapa) su potrošili 16/16 zahteva i nemaju nijednu sondu.
- **Uzrok:** sonde su išle poslednje, posle do 10 fajlova mape sajta i 7 stranica uzorka.
- **Odluka:** sonde idu pre uzorka, a `sitemap.max_files` je spušten sa 10 na 4.
  Budžet: početna 1 + robots 1 + sonde 2 + mape 4 + uzorak 7 = 15 od 16.
  Test: `test_velika_mapa_sajta_ne_pojede_sonde_za_lazni_404`.

### Nivo 2 visi zauvek na klinika.example (bag)

- **Zapažanje:** pun prolaz sa nivoom 2 nije se završio ni posle 10 minuta; 7 domena gotovo za ~30 s,
  klinika.example nikad. Javlja se povremeno, samo u punom prolazu.
- **Uzrok:** stek pokazuje da `_Recorder.drain()` čeka `response.body()` odgovora čije telo nikad ne stigne
  (strim, video). Nivo 2 nije imao tvrdi limit po domenu, pa je jedan takav odgovor blokirao ceo prolaz.
- **Odluka:** `drain` čeka najviše `browser.drain_timeout_s = 5`; šta ne stigne je nemereno, ne nula.
  Ceo nivo 2 po domenu ima tvrdi limit `browser.max_seconds_per_domain = 60`, posle kog je domen `failed`
  sa razlogom, a prolaz ide dalje. Testovi: `test_telo_koje_ne_stigne_je_nemereno_a_ne_zastoj`,
  `test_tvrdi_limit_po_domenu_prekida_nivo_2`.

### Posle obe popravke (automatski nivo)

`partial` 0 % (bilo 38 %), `unknown` 0 % (bilo 25 % za `infra.soft404`), najviše 15 od 16 zahteva.

Otvoreno za prolaz nad 100 domena:
- najsporiji domen je trošio 23,6 od 25 s budžeta — sporiji sajtovi će ga probijati;
- `perf.page.weight` pali na 7–8 od 8 domena. Ako tako ostane i na 100, prag od 1,5 MB ne razlikuje
  leadove i treba ga podići.

### klinika.example je `partial` — otvoreno

- **Zapažanje:** `perf.img.oversized` je `unknown` (17 od 33 slike nije izmereno), a kontrolni čist sajt
  ima 4 nalaza nivoa 2: `perf.page.weight`, `perf.load.time`, `perf.request.count`, `qa.console.errors`.
- **Odluka:** čeka ručnu proveru sajta u browser-u — da li su nalazi tačni, i zašto se pola slika ne učita
  posle skrolovanja.
