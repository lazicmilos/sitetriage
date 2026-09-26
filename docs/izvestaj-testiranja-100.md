# Izveštaj o testiranju — sistemski test nad 100 pravih domena

```
Naziv dokumenta:  Izveštaj o testiranju — skener, prolaz nad 100 domena
Oznaka:           IT-SKENER-001
Verzija:          1.0
Datum:            24.09.2026.
Autor:            Milos Lazic
Status:           Nacrt
```

| Verzija | Datum | Autor | Opis izmene |
|---|---|---|---|
| 1.0 | 24.09.2026. | Milos Lazic | Prvi prolaz nad 100 domena, nalazi i preporuka |

## 1. Predmet i obim

- **Predmet:** skener na grani `main` (commit `dddf810`), Docker slika sa Playwright 1.56.0 i Python 3.12.
- **Vrsta i nivo:** sistemsko testiranje na pravim podacima; nefunkcionalno (performanse, pouzdanost)
  i validacija (da li rangiranje daje dobre leadove).
- **Obim — jeste:** ceo tok `skener scan` (nivo 1, eskalacija, nivo 2, izveštaj) nad 100 domena iz
  stvarne liste leadova; nezavisna provera sumnjivih nalaza van alata (DNS, curl, ponovljeno merenje).
- **Obim — nije:** ručna provera svakog nalaza; prijemno testiranje (ručna ocena vrha liste — vidi §6).
- **Test podaci:** 100 domena malih firmi i udruženja iz Srbije. Delatnost je dodeljena po imenu domena,
  deo je pretpostavka. Lista i rezultati po domenu **nisu u repozitorijumu**: repozitorijum je javan, a
  lista sadrži poslovne kontakte i ocene tuđih sajtova. Ovde su samo zbirni brojevi.

## 2. Okruženje

Windows 10, Docker Desktop, slika `skener:dev`, kućna internet veza. Nivo 1: 8 domena istovremeno,
pauza 0,5–1 s između zahteva ka istom sajtu, budžet 16 zahteva i 25 s po domenu. Nivo 2: 3 konteksta
istovremeno, gornji limit 60 domena.

## 3. Izvršavanje

| | |
|---|---|
| Trajanje | 7 min 41 s (nivo 1: 211 s, nivo 2: 246 s za 60 domena) |
| Ulaz → izlaz | 100 domena → 100 redova u izveštaju |
| Log | 322 × INFO, 0 × WARNING, 0 × ERROR |
| Status | 62 `scanned`, 27 `partial`, 11 `failed` |
| Nivo 2 | 78 kandidata, 60 izmereno, 18 odsečeno limitom |

## 4. Izlazni kriterijumi

Kriterijumi su iz [`provera-na-pravim-sajtovima.md`](provera-na-pravim-sajtovima.md).

| Kriterijum | Granica | Rezultat | Ispunjen |
|---|---|---|---|
| padovi procesa | 0 | 0; svih 100 domena ima red u izveštaju | ✅ |
| vreme (U1) | 200 domena ≤ 15 min | 100 za 7,7 min; procena za 200: ~12 min (nivo 2 je ograničen na 60) | ✅ |
| `partial` među domenima koji rade | < 10 % | 27 od 89 = **30 %** | ❌ |
| `unknown` po proveri | < 20 % | najviše 7 % (provere duplikata) | ✅ |
| lažni pozitivi | nijedan poznat | **3 vrste** (BUG-003, BUG-004, BUG-006) | ❌ |
| prvih 5 ručno potvrđeno | da | čeka ručnu proveru | ⏳ |

## 5. Defekti

### Ispravljeni u ovom ciklusu (na ispitnom skupu od 8 domena)

| ID | Naslov | Ozbiljnost | Status |
|---|---|---|---|
| BUG-001 | Velika mapa sajta troši ceo budžet pre sondi za lažni 404 | major | Zatvoren — `partial` 38 % → 0 % |
| BUG-002 | Nivo 2 visi zauvek na odgovoru čije telo nikad ne stigne | blocker | Zatvoren — 3/3 prolaza završena |

### Otvoreni

```
ID: BUG-003   Naslov: Sajt koji blokira automatske posete dobija nalaze „nema robots.txt" i „nema sitemap"
Ozbiljnost: major   Prioritet: high
Okruženje: main dddf810, Docker, Windows 10
KORACI ZA REPRODUKCIJU
 1. Skenirati sajt koji na svaki zahtev vraća 403 sa stranom „Checking your browser before accessing".
OČEKIVANO   Domen je `failed`; robots i sitemap su `unknown` („pristup odbijen, ne zna se da li postoje").
STVARNO     `infra.sitemap.missing` (medium) i `infra.robots.missing` (low) — tvrdnje koje ne znamo.
UČESTALOST  2/2 takva sajta u prolazu
NAPOMENA    Obe provere svaki status ≠ 200 tumače kao „ne postoji". Samo 404 i 410 to znače;
            401, 403, 429 i 5xx znače da ne znamo.
```

```
ID: BUG-004   Naslov: Prekinuto TLS rukovanje se prijavljuje kao nevalidan sertifikat
Ozbiljnost: major   Prioritet: high
Okruženje: main dddf810, Docker (OpenSSL 3.0.13), Windows 10
KORACI ZA REPRODUKCIJU
 1. Skenirati sajt čiji server prekida TLS rukovanje sa Python klijentom
    (UNEXPECTED_EOF_WHILE_READING), a sa browserom i curl-om radi.
OČEKIVANO   `infra.tls.invalid` je `unknown`; alat pokušava http i skenira sajt.
STVARNO     `infra.tls.invalid` (high) — „sertifikat sajta nije valjan" — i domen `failed`.
            Nezavisna provera (curl): sertifikat je ispravan, sajt radi i preko https i preko http.
UČESTALOST  100 % (3/3 iz kontejnera)
NAPOMENA    `_classify` svaki `ssl.SSLError` svrstava u „tls"; nevalidan sertifikat je samo
            `ssl.SSLCertVerificationError`. Za „tls" se uz to ne pokušava http.
```

```
ID: BUG-005   Naslov: Limit nivoa 2 uvek odseca kandidate bez nalaza nivoa 1
Ozbiljnost: major   Prioritet: high
KORACI ZA REPRODUKCIJU
 1. Skenirati listu na kojoj je više od 60 kandidata za nivo 2.
OČEKIVANO   Sajt čiji je jedini signal na nivou 2 (spora početna, nema h1 u sirovom HTML-u)
            stiže na nivo 2 — to je smisao pravila iz §6 (b2b-firma.example).
STVARNO     Kandidati se biraju po skoru nivoa 1, pa sajtovi sa skorom 0 ispadaju prvi.
            U izveštaju stoje kao „0 nalaza", iako težina, vreme i h1 nisu ni mereni.
UČESTALOST  9 od 18 odsečenih kandidata nije imalo nijedan nalaz nivoa 1
NAPOMENA    `score.select_for_level2`. Posledica je lažno negativan rezultat na dnu liste.
```

```
ID: BUG-006   Naslov: Vreme učitavanja se meri dok tri sajta dele istu vezu
Ozbiljnost: major   Prioritet: high
KORACI ZA REPRODUKCIJU
 1. Iz prolaza uzeti 6 sajtova raspoređenih po izmerenom vremenu učitavanja.
 2. Izmeriti ih ponovo, jedan po jedan (`browser.concurrency = 1`).
OČEKIVANO   Isto vreme (± šum mreže) — broj koji ide klijentu mora da se odbrani.
STVARNO     U prolazu je vreme 1,1–4,6× duže (medijana 1,8×). Jedan sajt: 13,0 s u prolazu,
            2,8 s sam — `perf.load.time` (high) koji ne bi ni postojao. U prolazu 4 od 6 sajtova
            ima nalaz, a kad se mere sami 2 od 6.
UČESTALOST  6/6 ponovljenih merenja
NAPOMENA    Težina stranice je stabilna (5/6 identično) — osim kod sajta sa videom (vidi O-2).
```

## 6. Zapažanja za kalibraciju (odluke, ne defekti)

- **O-1: `perf.page.weight` ne razlikuje sajtove.** Preko 1,5 MB (prag za medium) ima 55 od 60
  izmerenih sajtova; medijana je 4,4 MB, p75 10,6 MB, p90 17,2 MB (merenje posle skrolovanja do dna).
  Vodeći nalaz je kod 15 od prvih 20 u rangiranju. Predlog: pragovi po raspodeli — medium > 5 MB,
  high > 10 MB, critical > 20 MB.
- **O-2: video menja težinu.** Kod 4 sajta video je najveći deo težine (najviše: 77 od 81 MB). Isti
  sajt sa videom izmeren je jednom 8,5, a drugi put 26,9 MB, jer se video skida koliko vreme merenja
  dozvoli. Predlog: video prikazati posebno u poruci i ne računati ga u prag.
- **O-3: poruka za `i18n.lang.mismatch` tvrdi više nego što je tačno.** Nalaz je tačan u 28 od 28
  slučajeva (WordPress sa `lang="en-US"` na srpskom sajtu). Ali poruka kaže da ga „pretraživači zato
  nude pogrešnom tržištu", a Google navodi da jezik stranice određuje iz vidljivog sadržaja i da `lang`
  atribut ne koristi. Pouzdan argument je čitač ekrana. Predlog: ispraviti poruku i preispitati `high`.
- **O-4: 30 % `partial` je posledica budžeta od 25 s.** 19 domena ga je potrošilo; na tim sajtovima je
  medijana odgovora po strani 1,1–3,2 s (spor deljeni hosting), pa 15 zahteva uz pauzu pristojnosti ne
  staje u 25 s. Predlog: 40 s. Broj zahteva ostaje 16, pa pristojnost ne trpi; procena za 200 domena
  i dalje je ispod 15 min.
- **O-5: sajt koji ne odgovara nema nalaz, a sajt bez DNS-a ima critical.** Oba znače „sajt se ne
  otvara". Predlog za v2: nalaz `infra.unreachable`.
- **O-6: 6 domena bez DNS zapisa** — potvrđeno van alata (6/6 NXDOMAIN). Alat je ovde tačan.

## 7. Zaključak i preporuka

Alat je **stabilan**: nijedan pad, svih 100 domena u izveštaju, u vremenskom okviru. Ali rangiranje
**još nije za slanje mejlova**: tri vrste lažnih nalaza (BUG-003, BUG-004, BUG-006), sistematski lažno
negativan rezultat za sajtove odsečene sa nivoa 2 (BUG-005), a vrh liste određuje prag koji pali skoro
svima (O-1).

**Ne preporučuje se prelazak na v2 dok BUG-003 do BUG-006 nisu rešeni i dok O-1 i O-4 nisu odlučeni.**
Posle toga: potvrdno testiranje svake ispravke, pa ponovljen isti prolaz nad istih 100 domena
(regresija) i ručna provera prvih 5 u rangiranju.

## 8. Naučene lekcije

- Lokalni server ne otkriva probleme tajminga, a 8 sajtova ne otkriva probleme raspodele. Tek na 100
  domena se videlo da prag težine pali skoro svima i da limit nivoa 2 odseca baš sajtove bez nalaza.
- Svaki broj koji ide klijentu treba proveriti van alata (DNS, curl, ponovljeno merenje) pre nego što
  mu se veruje. Tako su nađeni BUG-004 i BUG-006.
