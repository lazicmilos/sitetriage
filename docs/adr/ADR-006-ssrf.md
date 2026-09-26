# ADR-006: Skener ne otvara privatne adrese (zaštita od SSRF-a)

```
Status:  Prihvaćeno
Datum:   25.09.2026.
Autor:   Milos Lazic
```

## Kontekst

Skener otvara adrese koje zada korisnik. U komandnoj liniji to je lista samog operatera, ali u
web aplikaciji korisnik može da upiše `localhost`, `10.0.0.5` ili `169.254.169.254` i da preko
skenera pregleda server iznutra (Server-Side Request Forgery). Provera samog URL-a ne pomaže:
javno ime može da se razreši u privatnu adresu, može da se prebaci na nju između dva DNS upita
(DNS rebinding), a sajt može da preusmeri na nju.

## Odluka

Veza je dozvoljena samo ka globalnoj unicast adresi (`ipaddress.is_global` i nije multicast).
IPv4 upakovan u IPv6 (`::ffff:127.0.0.1`) sudi se kao IPv4. Izuzetak su samo `host:port` parovi
iz `[net] allowed_private`. Opšti prekidač koji isključuje zaštitu ne postoji. Klasifikacija
adresa je čista funkcija u `skener/addresses.py`, koju pokriva i mutaciono testiranje.

**Ulaz.** Domen sa IP adresom, portom ili korisničkim imenom ne dobija nijedan zahtev, osim kad
je `host:port` izričito dozvoljen. Takav domen je `failed` sa razlogom.

**Nivo 1.** `httpx` dobija sopstveni mrežni backend (`_JavneAdrese` u `fetch/http.py`). On
razrešava ime, proverava svaku adresu i otvara TCP vezu baš na proverenu adresu. SNI i `Host`
i dalje nose ime domena. Provera je na mestu gde se otvara veza, pa pokriva i svako
preusmerenje, a DNS rebinding ne prolazi. Blokiran domen je `failed` sa razlogom „adresa nije
javna", a ne „ne radi": sajt možda radi, samo ga namerno nismo otvorili.

`httpx` 0.28 nema javni parametar za mrežni backend, pa se postavlja kroz interno polje
`_pool._network_backend`. Ako ga nova verzija preimenuje, alat odbija da radi (`RuntimeError`),
a zaštita ne nestaje tiho. Klijent ne čita `HTTP(S)_PROXY` iz okruženja, jer proxy sam
razrešava ime i zaobišao bi proveru.

**Nivo 2.** `context.route("**/*")` za svaki zahtev browsera razrešava ime i propušta ga samo
ako su dozvoljene sve adrese, jer Chromium sam bira koju će koristiti. Šeme van `http` i `https`
se odbijaju, kao i ime koje ne može da se razreši. Kontekst ima `service_workers="block"`, jer
`route` ne vidi zahteve koje šalje service worker.

## Ograničenja nivoa 2

Nivo 2 je prva linija odbrane, a ne jedina:

1. **Preusmerenje.** `route` vidi samo prvu adresu, a ne i cilj preusmerenja. Provereno na
   Playwright 1.56: dozvoljena strana koja vraća 302 na privatni port odvede Chromium do tog
   porta. Test `test_browser_ne_prati_preusmerenje_na_privatnu_adresu` je označen kao
   `xfail(strict=True)`; kad Playwright počne da vidi preusmerenja, test pada i ova tačka se
   briše.
2. **Vreme između provere i veze.** Chromium sam razrešava ime, pa između naše provere i
   njegove veze postoji prozor u kom se DNS odgovor može promeniti.
3. **WebSocket.** `route` ne presreće WebSocket veze.

Nivo 2 ide samo na domene koji su prošli nivo 1, pa napadač mora da kontroliše javni sajt.
Web aplikacija u produkciji zato mora da ima i **filter izlaznog saobraćaja na nivou mreže**
(egress): radni proces sme da otvara samo javne adrese.

**Odluka vlasnika (25.09.2026.):** ograničenja nivoa 2 rešava filter izlaznog saobraćaja u web
fazi, kao obavezan deo produkcije. Lokalni proxy za Chromium, koji bi u samom alatu proveravao
svaku vezu, uključujući preusmerenja i WebSocket, ne pravi se: to je ozbiljan posao i menja
merenje vremena, a filter na nivou mreže pokriva sve tri rupe odjednom.

## Posledice

- Testovi otvaraju lokalni server na `127.0.0.1`. `conftest.py` dozvoljava tačno adrese
  servera koji rade, a server napravljen sa `dozvoljen=False` ostaje zabranjen, kao u
  produkciji.
- Staging sa portom radi samo uz izričitu dozvolu: `[net] allowed_private = ["staging.rs:8123"]`.
- `route` isključuje keš browsera i dodaje obradu po zahtevu. Kontekst je ionako nov za svaki
  domen, pa keša nije ni bilo, ali vreme učitavanja može malo da poraste. To se meri u
  kalibraciji na listi A.
