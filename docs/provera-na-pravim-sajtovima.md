# Provera na pravim sajtovima — uslov za v2

Svih 327 offline testova prolazi, ali nijedan nije dotakao pravi sajt. Fixture-i su ručno pisani, a
lokalni server odgovara za mikrosekunde. Četiri baga ispravljena pred ovu proveru (budžet, merenje
vremena, sonde, TLS dokaz) bila su nevidljiva baš zbog toga. Ova lista postoji da nađe **peti**.

Radi se lokalno, na mašini sa pravom mrežom. Rezultat nije „prošlo/palo", nego `docs/kalibracija.md`.

## 0. Priprema (10 min, prvi build povlači ~2 GB)

Sve ide kroz Docker: ista slika, ista verzija Chromium-a i Python-a kao u CI-ju. Ako se
tvoj rezultat razlikuje od mog, razlika je u mreži i sajtovima, ne u okruženju.

```bash
git pull
mkdir -p rad                                    # ulaz i izlaz; kod ostaje u slici
export SKENER_NAZIV="Ime operatera" SKENER_KONTAKT="kontakt@primer.rs"  # ko skenira; bez ovoga nema zahteva
export SKENER_UID=$(id -u) SKENER_GID=$(id -g)  # Linux: da izveštaji pripadaju tebi
docker compose build
docker compose run --rm skener pytest -q        # svi testovi moraju da prođu pre ičega drugog
```

U PowerShell-u se identitet postavlja sa `$env:SKENER_NAZIV = "Ime operatera"` i
`$env:SKENER_KONTAKT = "kontakt@primer.rs"`, a `SKENER_UID` ti na Windows-u ne treba.

Ako ijedan test preskoči sa „Chromium se ne pokreće", slika nije dobra i dalje se ne ide.

## 1. Ispitni skup: specifikacija naspram stvarnosti (10 min)

```bash
docker compose run --rm skener pytest -m live -v 2>&1 | tee rad/live.txt
docker compose run --rm skener skener record domains.example.csv --out /rad/snimci
docker compose run --rm skener python scripts/metrike.py /rad/snimci | tee rad/metrike-ispitni.txt
```

`record` namerno ne piše preko `tests/fixtures/`: prvo gledamo razliku, pa tek onda menjamo fixture-e.

Svaki pad u `live.txt` je jedno od tri, i treba reći koje:

| Uzrok | Primer | Šta se radi |
|---|---|---|
| sajt se promenio | Institucija popravila canonical | beleška u `kalibracija.md`; fixture se osvežava |
| prag je loš | `lang.mismatch` ne pali na očigledno srpskom sajtu | izmena u `skener.toml`, proveri sa `recheck` |
| bag | provera kaže `ok`, a ručno vidiš problem | test koji pada + popravka, kao B1–B4 |

## 2. Pravi prolaz: 30–50 domena iz tvoje liste leadova (20 min)

Stavi listu u `rad/leads.csv` (zaglavlje `domain,industry,note`).

```bash
time docker compose run --rm skener skener scan /rad/leads.csv --out /rad/izvestaj 2>&1 | tee rad/prolaz.log
docker compose run --rm skener python scripts/metrike.py /rad/izvestaj/snapshots | tee rad/metrike.txt
```

Kad neki domen izgleda čudno:

```bash
docker compose run --rm skener skener scan /rad/leads.csv --only cudan.rs --debug-domain cudan.rs --out /rad/debug
```

## 3. Kriterijumi — uslov za v2

| Metrika | Granica | Zašto baš ta |
|---|---|---|
| padovi procesa | **0** | U2: koliko domena uđe, toliko redova izađe |
| `partial` među domenima koji rade | **< 10 %** | iznad toga budžet ili prag ne odgovara stvarnosti |
| `unknown` za jednu proveru | **< 20 %** živih domena | proveru koja najčešće ne zna ne treba ni imati |
| vreme za 50 domena | **< 4 min** | linearno do U1: 200 domena ≤ 15 min |
| klinika.example | **≤ 2 nalaza** | U4: kontrolni čist sajt |
| prvih 5 u rangiranju | **ručno potvrđeni** | ako #1 nije bolji lead od #10, rangiranje ne radi svoj posao |

Za ručnu potvrdu otvori sajt, uporedi sa `message_client` iz `findings.csv`, i za svaki nalaz zapiši:
tačan / lažno pozitivan / tačan ali nebitan. Isto za poslednjih 5, da proveriš da nisu promašeni loši sajtovi.

## 4. Šta mi šalješ nazad

1. `rad/live.txt`
2. `rad/metrike-ispitni.txt` i `rad/metrike.txt`
3. `rad/izvestaj/summary.csv` i `rad/izvestaj/findings.csv`
4. ručne ocene za prvih 5 i poslednjih 5
5. sve što ti je zapalo za oko, čak i ako ne umeš da objasniš zašto

Snapshote ne šalji. Sadrže sirovi HTML tuđih sajtova, a sve što nam treba iz njih daje `metrike.py`.

## 5. Posle toga

Svaka odluka ide u `docs/kalibracija.md` u obliku **prag — zapažanje — odluka**. Pragovi se probaju u
`rad/kalibracija.toml`, koji sadrži samo ono što menjaš, jer se `--config` spaja preko `skener.toml`.
Tako nema rebuild-a slike između dva pokušaja, a nema ni ponovnog skidanja sajtova:

```bash
docker compose run --rm skener skener recheck /rad/izvestaj/snapshots --config /rad/kalibracija.toml --out /rad/novi
```

Kad je prag odlučen, prenosi se u `skener.toml` i ide u commit.

Tek kad su svi kriterijumi iz tačke 3 zeleni: novi snimak u `tests/fixtures/`, `git diff`, i v2.
