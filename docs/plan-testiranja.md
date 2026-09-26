# Plan testiranja — skener

```
Oznaka:    PT-SKENER-001
Verzija:   2.0
Datum:     25.09.2026.
Autor:     Milos Lazic
Status:    Nacrt
```

| Verzija | Datum | Autor | Opis izmene |
|---|---|---|---|
| 1.0 | 24.09.2026. | Milos Lazic | Ciklus ispravki posle prvog prolaza nad 100 domena (IT-SKENER-002) |
| 2.0 | 25.09.2026. | Milos Lazic | Ciklus v2: pooštreni pragovi kvaliteta, liste A i B, podeljen kriterijum za `partial` |

## 1. Uvod

Plan pokriva razvoj v2: ispravke otvorenih zapažanja iz
[`izvestaj-testiranja-100.md`](izvestaj-testiranja-100.md) i
[`izvestaj-testiranja-2.md`](izvestaj-testiranja-2.md), izdvajanje jezgra iz CLI-ja, JSON izveštaj,
poruke na srpskom i engleskom, zaštitu od SSRF-a, merenje pod fiksnim mrežnim profilom i komande
`diff` i `outcomes`. Pravila i pragovi koje alat mora da poštuje su u README-u (tabela provera je
izvedena iz registra) i u `skener.toml`.

## 2. Kontekst

- **Predmet:** skener na grani `main`, verzija `2.0.0.dev0` do izdanja, Docker slika sa Playwright
  1.56.0 i Python 3.12.
- **Obim — jeste:** sve provere nivoa 1 i 2, bodovanje, rangiranje, politika eskalacije, fetcher
  (budžet, semafori, greške, SSRF), merenje u browseru, pipeline, CLI (`scan`, `recheck`, `record`,
  `explain`, `diff`, `outcomes`), konfiguracija, izveštaji (HTML, CSV, JSON), ulazni CSV, poruke za
  klijenta na oba jezika.
- **Obim — nije:** opterećenje tuđih sajtova (alat je namerno pristojan i nije predmet testa
  opterećenja); bezbednost samog Chromium-a; pravna usklađenost načina na koji kupac koristi izveštaj;
  web aplikacija.
- **Pretpostavke:** testovi ne zavise od mreže, osim onih označenih sa `live`; pravi prolaz radi
  operater sa svoje veze.

## 3. Strategija

| Nivo | Šta | Alat | Kada |
|---|---|---|---|
| jedinično | provere nad snapshotima, bodovanje, normalizacija URL-a, konfiguracija, poruke, klasifikacija adresa | pytest | svaki commit (CI) |
| integraciono | fetcher i browser protiv lokalnog servera; pipeline i CLI od kraja do kraja | pytest, pravi Chromium | svaki commit (CI, i u Docker slici) |
| sistemsko | ceo prolaz nad listom A (kalibracija), zatim nad listom B (validacija) | `skener scan` u Docker-u | pred izdanje v2 |
| prijemno | ručna ocena prvih 10 i poslednjih 5 u rangiranju na listi B | vlasnik proizvoda | pred izdanje v2 |

Lista A je istih 100 domena iz IT-SKENER-001 i IT-SKENER-002. Na njoj se kalibrišu pragovi. Lista B
je 100 novih domena istog tipa, bez preklapanja sa A, i na njoj se mere izlazni kriterijumi. Posle
kalibracije na A pragovi su zamrznuti do kraja merenja na B, jer bi štimovanje prema B od nje napravilo
novu A.

**Tehnike**, redom iz skripte: klase ekvivalencije, granične vrednosti (za svaki prag iz README-a,
trotačkasto), tabele odlučivanja (eskalacija, status domena, izbor za nivo 2, statusi sondi i fajlova),
prelazi stanja (ulazni zahtev: https, sertifikat, rukovanje, http, DNS), negativni testovi, pogađanje
grešaka (ćirilica, Excel CSV, nule u konfiguraciji), merenje pokrivenosti grana i mutaciono testiranje.
Svaki parametrizovani slučaj nosi `id` sa tehnikom: `ke-` klasa ekvivalencije, `gv-` granična vrednost,
`tab-` tabela odlučivanja, `st-` prelaz stanja, `nv-` nevažeća klasa, `pg-` pogađanje grešaka.

**Statičko testiranje:** recenzija svih rečenica za klijenta, na oba jezika. Svaka tvrdnja mora biti
tačna i proverljiva, a svaki broj mora poticati iz dokaza.

**Test podaci:** sintetički snapshoti (`tests/factories.py`), lokalni server (`tests/localserver.py`),
ručno pisani ispitni skup (`tests/fixtures/`). Liste A i B, rezultati po domenu, ishodi leadova i
popunjeni obrasci ručne provere ostaju van repozitorijuma (`rad/`), jer sadrže poslovne kontakte.

## 4. Kriterijumi

**Ulazni:** Docker slika se gradi; postojeći testovi prolaze; svaka izmena ponašanja ima test koji je
pao pre izmene.

**Obustava:** pad procesa ili zastoj u pravom prolazu. Prolaz se prekida, a defekt se prijavljuje i
ispravlja pre nastavka.

**Izlazni** (svi moraju biti ispunjeni):

| Kriterijum | Granica | Gde se meri |
|---|---|---|
| automatizovani testovi | 100 % prolazi, u Docker slici i u CI-ju | CI |
| pokrivenost linija i grana | ≥ 95 % (CI pada ispod); nijedan modul ne pada; novi moduli ≥ 95 % | CI |
| mutacioni skor | ≥ 90 % neekvivalentnih; preživeli razvrstani kao u IT-SKENER-002 §3.2 | Docker |
| `ruff` | čist | CI |
| katalog poruka | potpun za `sr` i `en`; recenzija vlasnika urađena | CI + vlasnik |
| JSON | izlaz prolazi šemu; `diff` istog izveštaja je prazan | CI |
| SSRF | svi testovi graničnih vrednosti i integracioni testovi prolaze | CI |
| padovi | 0 | A i B |
| WARNING i ERROR u logu | 0 neobjašnjenih | A i B |
| `partial` zbog budžeta | < 10 % domena koji rade | B |
| `unknown` po proveri | < 20 % za svaku proveru | B |
| lažni nalazi | nijedan poznat | B, ručna provera |
| sajtovi koji ne rade u rangiranju | 0 | A i B |
| ponovljivost težine i broja zahteva do `load` | ≤ 10 % razlike kod ≥ 9 od 10 sajtova | A |
| vreme u prolazu / vreme kad se sajt meri sam | 0,8–1,25, ako je paralelno učitavanje uključeno | A |
| procena za 200 domena | ≤ 15 min | A i B |
| prvih 10 na B | 0 netačnih nalaza; ≥ 7 od 10 „poslao bih" | ručna provera |
| poslednjih 5 na B | 0 promašenih ozbiljnih problema; svaki promašaj je defekt, a posle ispravke se meri ponovo | ručna provera |
| otvorena zapažanja | O-5 i O-7 … O-12 zatvorena ili izričito prebačena van obima | IT-SKENER-003 |

Kriterijum `partial` < 10 % iz verzije 1.0 podeljen je na dva. Alat namerno kaže `unknown` kad
nešto ne može da dokaže, pa `partial` meša kvar (potrošen budžet) sa iskrenim „ne znam"
(IT-SKENER-002, O-7).

## 5. Organizacija

Autor testova i izvršilac: razvoj. Prave prolaze nad listama A i B pokreće vlasnik, sa svojim
identitetom. Prijemna ocena rangiranja: vlasnik proizvoda. Defekti se vode u izveštaju o testiranju,
u formatu iz skripte (BUG-xxx).

## 6. Raspored

1. F0, priprema: kraj reda, verzija, pragovi kvaliteta.
2. F1, jezgro: pipeline, čitanje liste, katalog poruka, JSON, SSRF, izuzeti domeni.
3. F2, tačnost: zatvaranje zapažanja O-5 i O-7 … O-12.
4. F3, merenje: fiksni mrežni profil, paralelno učitavanje, trajanje prolaza.
5. F4, poslovni sloj: `diff` i `outcomes`.
6. F5, validacija: kalibracija na A, prolaz na B, ručna provera, izveštaj IT-SKENER-003.

## 7. Rizici testiranja

| ID | Rizik | V | U | Mera |
|---|---|---|---|---|
| R1 | pravi sajtovi se menjaju između dva prolaza, pa razlika nije samo posledica ispravki | 4 | 3 | poređenje po grupama nalaza, ne po domenu; sumnjivo se proverava van alata |
| R2 | testovi sa vremenom (pauze, budžet) su nestabilni na sporoj mašini | 2 | 3 | vreme se proverava sa marginom, a mehanizam preko redosleda događaja |
| R3 | mutaciono testiranje traje predugo | 3 | 2 | samo moduli sa logikom; ostalo pokriva integraciono testiranje |
| R4 | lista leadova procuri u javni repozitorijum | 2 | 5 | `rad/` je u `.gitignore`; izveštaji sadrže samo zbirne brojeve |
| R5 | kalibracija na A se prelije na B | 3 | 4 | pragovi zamrznuti posle kalibracije; defekt nađen na B ide kroz BUG proceduru |
| R6 | refaktor poruka neprimetno promeni srpske rečenice | 3 | 4 | golden fajl svih rečenica pre refaktora |

## 8. Upravljanje defektima

Ozbiljnost: blocker (prolaz stane), critical (pogrešan rezultat za sve), major (lažan nalaz ili
lažno negativan rezultat za klijenta), minor, trivial. Prioritet određuje uticaj na kupca.
Životni ciklus: Novi → Ispravljen → Potvrdno testiran → Zatvoren.

## 9. Isporuke

Testovi u `tests/`, ovaj plan, izveštaj o testiranju IT-SKENER-003, merenja pokrivenosti i mutacionog
testiranja, obrazac ručne provere (`docs/obrazac-rucne-provere.md`).

## 10. Odobrenja

Vlasnik proizvoda odobrava izdanje `v2.0.0` na osnovu izveštaja o testiranju.
