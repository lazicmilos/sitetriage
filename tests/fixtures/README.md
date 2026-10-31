# Fixture-i ispitnog skupa

**Ovi snapshoti su ručno napisani, nisu snimljeni sa pravih sajtova.**

Napravljeni su bez pristupa mreži, generatorom [`../make_fixtures.py`](../make_fixtures.py), i
opisuju stanje koje §12.4 specifikacije zadaje za osam tipičnih sajtova. Domeni su izmišljeni,
pod rezervisanim TLD-om `.example` (RFC 2606) — nijedan ne pripada stvarnom sajtu.

Šta zato jesu, a šta nisu:

- **Jesu** provera da lanac `snapshot → provere → bodovanje → rangiranje` daje očekivane
  `check_id`-eve i tačne brojeve iz §9.4.
- **Nisu** provera da je ijedan pravi sajt u tom stanju. Za to služi `pytest -m live` nad
  tvojom listom domena (`SKENER_LIVE_CSV`, vidi [`../test_live.py`](../test_live.py)).

Posle izmene generatora napravi ih ponovo:

```bash
python tests/make_fixtures.py
```

Generator piše gzip bez vremena u zaglavlju, pa `git diff` pokazuje samo stvarne izmene.
