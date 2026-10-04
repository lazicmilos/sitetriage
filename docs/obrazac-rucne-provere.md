# Obrazac ručne provere — lista B (Z-52)

Ručna provera je prijemni test v2 (docs/plan-testiranja.md). Radi je vlasnik proizvoda nad izveštajem
iz prolaza nad listom B. Ovde je prazan obrazac. Popunjen primerak sadrži domene, pa ostaje u
`rad/` (pravilo 7) i ne ulazi u repozitorijum, a u IT-SKENER-003 idu samo zbirni brojevi.

## Pre početka

- Kopiraj ovaj fajl u `rad/rucna-provera-b.md` i popunjavaj kopiju.
- Proveravaj što pre posle prolaza, najkasnije u roku od 3 dana. Sajtovi se menjaju, a nalaz se
  ocenjuje prema stanju sajta u trenutku skeniranja. Ako se sajt u međuvremenu promenio, zapiši to
  u napomenu i nalaz ne računaj ni kao tačan ni kao netačan.
- Nalaz proveravaš van alata: `curl` (uvek sa `--max-time 20`), browser na telefonu i na računaru,
  DNS (`Resolve-DnsName`). Rečenicu za klijenta čitaš iz `findings.csv` (`message_client`), a
  izmerene brojeve iz `evidence_json`.

**Tačan nalaz** je nalaz čija rečenica za klijenta stoji na sajtu: svaki broj u njoj odgovara onome
što vidiš ili izmeriš, a problem postoji. **Netačan nalaz** je nalaz čija rečenica ne stoji, makar i
delimično (pogrešan broj, pogrešna stranica, problema nema). Svaki netačan nalaz je defekt i ide kroz
BUG proceduru (docs/izvestaj-testiranja-2.md §5).

Podaci o prolazu:

| | |
|---|---|
| datum prolaza | |
| verzija alata (`scanner_version` iz `report.json`) | |
| otisak konfiguracije (`config_digest`) | |
| datum provere | |
| proverio | |

## 1. Prvih 10 u rangiranju

Za svaki domen jedna tabela. Redovi su nalazi iz `findings.csv` za taj domen.

**Mesto 1** — domen: ______________________ delatnost: ______________

| `check_id` | Tačan / netačan | Kako je provereno | Napomena |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

Da li bih ovom sajtu poslao mejl: **da / ne / možda**. Zašto:

(ponoviti za mesta 2–10)

## 2. Poslednjih 5 u rangiranju

Otvori sajt i potraži očigledan ozbiljan problem koji alat nije prijavio: sajt se ne otvara na
telefonu, učitava se veoma sporo, nema https, stranice vraćaju grešku, sadržaj je prazan ili
pokvaren. Za svaki problem zapiši i koja provera je trebalo da ga nađe. Ako ga ne pokriva nijedna
provera iz `skener explain --all`, upiši „—".

| Mesto | Domen | Ozbiljan problem koji alat nije našao | Provera koja je trebalo da ga nađe | Kako je provereno |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |

Svaki promašaj je defekt lažno negativnog tipa (kao BUG-005) i dobija analizu uzroka. Posle ispravke
se kriterijumi ponovo mere na B.

## 3. Zbir

| Kriterijum (spec §7) | Granica | Rezultat |
|---|---|---|
| netačnih nalaza u prvih 10 | 0 | |
| „poslao bih" (da) u prvih 10 | ≥ 7 od 10 | |
| promašenih ozbiljnih problema u poslednjih 5 | 0 | |

Otvoreni defekti (BUG-xxx) i zapažanja:
