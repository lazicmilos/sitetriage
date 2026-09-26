# Fixture-i ispitnog skupa

**Ovi snapshoti su ručno napisani, nisu snimljeni sa pravih sajtova.**

Napravljeni su bez pristupa mreži, generatorom [`../make_fixtures.py`](../make_fixtures.py), i
opisuju ono što §12.4 specifikacije tvrdi da je na tih osam domena — **ne ono što je tamo danas**.

Šta zato jesu, a šta nisu:

- **Jesu** provera da lanac `snapshot → provere → bodovanje → rangiranje` daje očekivane
  `check_id`-eve i tačne brojeve iz §9.4.
- **Nisu** provera da su ti domeni zaista u tom stanju. Za to služi `pytest -m live`.

Zameni ih pravim snimcima čim budeš imao mrežu:

```bash
skener record domains.example.csv --out tests/fixtures/
```

pa pogledaj `git diff` — razlika pokazuje šta se na sajtovima promenilo otkad su poslednji put
snimljeni, a to je samo po sebi korisna informacija za prodaju.
