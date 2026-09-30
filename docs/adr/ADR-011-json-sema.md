# ADR-011: `report.json` je ugovor sa šemom i verzijom

```
Status:  Predloženo
Datum:   30.09.2026.
Autor:   Milos Lazic
```

## Kontekst

HTML i CSV su za ljude. Web aplikacija, `skener diff`, CRM i kupac koda čitaju izlaz programom, i
njima treba oblik koji se ne menja tiho. U v1 takvog izlaza nije bilo, pa bi svaka izmena modela
neprimetno pokvarila onoga ko čita.

## Odluka

- `report.json` je serijalizovan `ScanResult` (Z-13). Polja se zovu kao u `models.py`. Nalaz nema
  rečenicu, nego `check_id`, dokaz i `variant`, a rečenicu pravi čitalac na svom jeziku
  ([ADR-009](ADR-009-katalog-poruka.md)).
- Oblik opisuje šema `skener/schema/report-2.json`, koja ide uz paket. Šema ne dozvoljava nepoznata
  polja, pa novo polje mora prvo u šemu, a test validira izlaz (`test_json_izvestaj_prolazi_semu`).
- `schema_version` je prvo polje. Dodato polje podiže drugi broj (`2.0` → `2.1`), jer ga stari
  čitalac može preskočiti. Obrisano polje, promenjen tip ili značenje polja i preimenovan `check_id`
  podižu prvi broj (`2.x` → `3.0`).
- `config_digest` je sha256 konfiguracije koja utiče na rezultat, bez identiteta, paralelizma i
  putanje do browsera. `diff` po njemu zna da li je razlika između dva prolaza od sajta ili od
  pragova (`test_otisak_ne_zavisi_od_identiteta_i_paralelizma`,
  `test_otisak_se_menja_kad_se_promeni_prag`).
- Snapshoti iz v1 ostaju čitljivi. Provera kojoj fali polje uvedeno u v2 daje `unknown` sa
  razlogom, nikad `ok` i nikad pad (`test_v1_snapshot_daje_unknown_a_ne_pad`).
- Do izdanja `v2.0.0` šema je `2.0` i menja se bez podizanja verzije, jer je niko spolja ne čita.
  Tako su dodati `environment.network_profile` (Z-30) i `environment.link_mbps` (Z-33). Pravila
  promene važe od izdanja.

## Posledice

- Svako novo polje u modelu traži izmenu šeme u istom commit-u, inače test pada.
- Izmena koja lomi kompatibilnost ide u CHANGELOG, u odeljak „Izmene koje lome kompatibilnost".
- `diff` (F4) odbija da poredi izveštaje sa različitim prvim brojem šeme.
- Šema opisuje izveštaj, ne snapshot. Snapshot je interni format alata i može da se menja, dok god
  ga `recheck` čita.
