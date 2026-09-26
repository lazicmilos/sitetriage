# ADR-009: Rečenice se prave pri prikazu, iz kataloga

```
Status:  Prihvaćeno
Datum:   25.09.2026.
Autor:   Milos Lazic
```

## Kontekst

Rečenica za klijenta pravila se u trenutku provere (`registry.finding` → `message_template.format`),
na srpskom, i čuvala se u nalazu. Dokaz je već sadržao složene srpske oblike („3 kopije",
„(video dodatno 8 MB)", „175 odvojenih preuzimanja"). Takav nalaz ne može da se prikaže na
engleskom, `diff` između dva prolaza bi poredio tekst umesto merenja, a stari prolaz ne može da
dobije ispravljenu rečenicu.

## Odluka

- `Finding` nosi `check_id`, dokaz i opcioni `variant`, a ne rečenicu. Rečenicu pravi
  `skener.messages.render(finding, lang)` pri prikazu.
- Katalog je po jeziku (`skener/messages/sr.py`, `en.py`). Sadrži klijentsku i tehničku rečenicu
  za svaku proveru, oznake HTML izveštaja, nacrt mejla i nazive tehničkih kodova iz dokaza.
- Šablon je običan `str.format`, uz dva dodatka: `{broj:n:oblik|oblik|oblik}` za broj i
  imenicu (srpski tri oblika, engleski dva) i `{lista:join: → }`. Decimalni broj u rečenici za
  klijenta piše se po jeziku; tehnička rečenica ga ostavlja kakav jeste.
- Dokaz sadrži samo brojeve, logičke vrednosti, URL-ove, tehničke kodove, sirove poruke grešaka i
  tekst preuzet sa sajta (naslov, opis). Test dozvoljava rečenicu sa razmakom samo pod tim
  ključevima.
- Provera sa više oblika rečenice bira oblik preko `variant`, na primer težina sa videom i bez
  njega.
- Pre izmene je napravljen golden fajl (`tests/golden/poruke-sr.json`): 92 srpske rečenice za
  svih 28 provera, sa ispitnog skupa i iz slučajeva koji menjaju oblik rečenice. Posle izmene
  katalog daje iste rečenice.

## Posledice

- `--lang sr|en` važi za `scan`, `recheck` i izveštaje, a `skener explain` ispisuje oba jezika.
- Nova provera traži unos u oba kataloga; test pada ako neki fali ili ako jezik ima višak.
- Engleska rečenica ne sme da tvrdi više od srpske. Isti testovi važe za oba jezika, a
  englesku verziju pregleda vlasnik.
- Razlozi za `unknown` i razlozi eskalacije isto su kod i podaci (`Reason`), a rečenicu pravi
  `skener.messages.reason` (odluka vlasnika od 25.09.2026.). Golden fajl
  `tests/golden/razlozi-sr.json` čuva srpske rečenice kakve su bile pre izmene.
- Dokaz se promenio: nestali su složeni oblici, `uzorak` je kod (`sitemap`, `links`), nedostajuće
  kodiranje je `null`, a lanac preusmerenja je lista. To je izmena koja lomi kompatibilnost i
  upisana je u CHANGELOG.
