# ADR-010: Nivo 2 meri pod fiksnim mrežnim profilom, bez izolacije sajtova

```
Status:  Predlog
Datum:   27.09.2026.
Autor:   Milos Lazic
```

## Kontekst

Vreme učitavanja zavisi od veze sa koje se meri. Kućna veza, server u data centru i kupčeva
mašina daju različite brojeve za isti sajt, pa bi isti sajt kod jednog dobio nalaz, a kod drugog
ne. Rečenice o sekundama već računaju sa vezom od 4,8 Mb/s, pa merenje treba da koristi istu
(SP-SKENER-002, Z-30).

Chromium profil mreže prima po cilju (target): `Network.emulateNetworkConditions` na sesiji
stranice. Pun Chromium, kakav je i sistemski Chrome, učitava iframe sa drugog sajta (YouTube,
mape) u poseban proces (OOPIF), a to je poseban cilj koji profil stranice ne usporava. Proba
27.09.2026. je to potvrdila na Chromium-u 141: stranica sa iframe-om od 600 kB učitana je za
274 ms, a bez OOPIF-a za 1397 ms. Playwright-ov headless shell iframe drži u istom procesu, pa bi
problem ostao sakriven sve dok se ne uključi `SKENER_CHROMIUM`.

Profil može da se postavi i na svaki cilj posebno (`Target.setAutoAttach`), ali Playwright-ova
`CDPSession` ne šalje komande sesijama dece. Postavljanje profila na iframe tek kad se pojavi
kasni za prvim zahtevom iframe-a.

## Odluka

- `[network_profile]` u `skener.toml` (`download_mbps`, `upload_mbps`, `latency_ms`) je jedini
  izvor brzine: iz njega ide profil za Chromium i sekunde u rečenicama za klijenta.
  `thresholds.perf.mobile_speed_mbps` je obrisan.
- Svaki kontekst nivoa 2, pre navigacije, dobija CDP `Network.emulateNetworkConditions`. Protok je
  u bajtovima u sekundi: 4,8 Mb/s = 600 000 B/s.
- Chromium se pokreće sa `--disable-site-isolation-trials`, pa su iframe-ovi u procesu stranice i
  profil važi i za njih. Test `test_profil_vazi_i_za_iframe_sa_drugog_porekla` koristi pun
  Chromium i pada bez ove zastavice.
- Profil se čuva u `BrowserSnapshot.network_profile` i u `environment` JSON izveštaja.
  `perf.load.time` ga navodi u rečenici („na simuliranoj vezi od 4,8 Mb/s"). Snimak bez profila
  meren je na stvarnoj vezi, pa je vreme za njega `unknown`.
- CPU se ne emulira.

## Posledice

- Isti sajt daje isto vreme na svakoj mašini, do razlike u procesoru. README to navodi.
- Izolacija sajtova štiti podatke jednog sajta od koda drugog u istom procesu. Skener ne nosi
  prijave ni kolačiće vredne zaštite, a svaki domen dobija nov kontekst. Ako se to promeni (na
  primer, nivo 2 sa prijavom korisnika u web fazi), ova odluka se preispituje.
- Pragovi `load_ms`, `browser.timeout_s` i `browser.max_seconds_per_domain` su kalibrisani na
  stvarnoj vezi. Pod profilom će vremena biti duža, pa se ti pragovi određuju u Z-50, iz raspodele
  izmerene pod profilom. Duže učitavanje produžava i nivo 2 (rizik R-1). To rešavaju Z-31 i Z-32.
