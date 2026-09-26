# ADR-008: Prolaz kao funkcija jezgra, ne komandne linije

```
Status:  Prihvaćeno
Datum:   25.09.2026.
Autor:   Milos Lazic
```

## Kontekst

Redosled nivo 1 → eskalacija → izbor → nivo 2 → bodovanje → rangiranje postojao je samo u `cli.py`.
Web worker bi morao da ga kopira, a dve kopije istog redosleda se vremenom raziđu. Uz to je svaki
nivo pokretao svoj `asyncio.run`, a nivo 2 je petlji postavljao rukovalac izuzetaka (BUG-007) i
nije ga vraćao. U procesu koji dugo živi to trajno menja globalno stanje.

## Odluka

Ceo prolaz je u modulu `skener.pipeline`:

```python
async def scan(targets, config, *, level="auto", snapshot_dir=None, on_event=None) -> ScanResult
def recheck(snapshot_dir, config, *, on_event=None) -> ScanResult
async def record(targets, config, *, out_dir, level="auto") -> int
```

- `scan` je jedna async funkcija i radi u jednoj petlji. Pozivalac je pokreće sa `asyncio.run`
  (CLI) ili u svojoj petlji (worker).
- Pipeline ne štampa, ne čita argumente i ne izlazi iz procesa. Greške su `ConfigError` i
  `InputError`, a šta se s njima radi odlučuje pozivalac.
- Napredak ide kroz `on_event(Event)`: faza počela, domen završen, faza završena, uz brojač
  `done`/`total`. Greška u toj funkciji se loguje i prolaz ide dalje.
- Otkazan prolaz (`CancelledError`) izlazi napolje. Browser i HTTP klijent se zatvaraju u `finally`,
  a snapshoti završenih domena ostaju na disku.
- Nivo 2 postavlja svoj rukovalac izuzetaka samo dok traje, a zatim vraća prethodni.
- `cli.py` ne uvozi `fetch.http`, `fetch.browser` ni `score`, što proverava
  `tests/test_arhitektura.py`.

## Posledice

- CLI i worker dele isti kod, pa isti ulaz daje isto rangiranje. Test pariteta poredi
  `pipeline.recheck` sa putem kojim je `recheck` išao pre ove odluke.
- `ScanResult` je osnova JSON izveštaja, pa JSON opisuje ono što pipeline stvarno vraća.
- Snapshoti se i dalje pišu čim je domen gotov. Otkazivanje ne briše već urađen posao.
- Fetcheri dobijaju povratni poziv `on_done` po domenu. To je jedina izmena u njihovom
  interfejsu.
