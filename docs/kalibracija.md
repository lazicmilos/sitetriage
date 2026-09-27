# Kalibracija

Dnevnik odluka iz provera na pravim sajtovima. Oblik: **zapažanje — uzrok — odluka**.
Kako se provera radi, piše u [`provera-na-pravim-sajtovima.md`](provera-na-pravim-sajtovima.md).

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
  izolacije sajtova ([ADR-010](adr/ADR-010-mrezni-profil.md)). Pragovi `load_ms` (4 / 8 s),
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
- **Odluka:** alat radi ispravno. Oba nalaza su u `POPRAVLJENO` u `tests/test_live.py`; fixture-i ostaju kao u specifikaciji.

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
