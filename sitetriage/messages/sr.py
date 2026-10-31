"""Serbian catalog. A sentence goes straight into an email, so it must be accurate and
grammatical (ADR-022).

The sentences, labels and reasons are the Serbian locale and stay in Serbian; only the code
around them is in English.
"""

from __future__ import annotations


def decimal(number: float) -> str:
    """„14,9", „22", „0,1": a decimal comma and no „,0", as written in an email (BUG-015)."""
    return f"{number:.1f}".removesuffix(".0").replace(".", ",")


def form(number: int, singular: str, paucal: str, plural: str) -> str:
    """Serbian picks the form by the last digit, except for 11–14: singular after 1 (but not
    11), paucal after 2–4 (but not 12–14), plural for everything else. The template supplies
    the forms, because they also depend on the case: „ima 21 grešku", but „od 21 slike".
    """
    if number % 10 == 1 and number % 100 != 11:
        return singular
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return paucal
    return plural


def with_number(number: int, singular: str, paucal: str, plural: str) -> str:
    """„1 stranica", „3 stranice", „5 stranica", „21 stranica", „12 stranica"."""
    return f"{number} {form(number, singular, paucal, plural)}"


def plural(number: int, forms: list[str]) -> str:
    return form(number, *forms)


DECIMAL = decimal

# Technical codes from the evidence, as they read in a sentence.
CODES: dict[str, dict[object, str]] = {
    "encoding": {None: "nema"},
    "error": {"unknown": "nepoznata"},
    "kind": {
        None: "nepoznato",
        "dns_temporary": "DNS privremeno nedostupan",
        "blocked": "zaštita od SSRF-a",
    },
    "sample": {"sitemap": "sitemap", "links": "interni linkovi sa početne", "none": "samo početna"},
    "source": {"raw_html": "sirovi HTML", "rendered": "stranica posle JavaScript-a"},
    "cause": {
        "dns": "domen nema zapis koji ga povezuje sa serverom",
        "no_response": "server nije prihvatio vezu ni preko https ni preko http",
    },
}

_WEIGHT = (
    "Na sporijoj mobilnoj vezi ({speed_mbps} Mb/s) za to je potrebno oko {seconds} s."
)

FINDINGS: dict[str, dict] = {
    # ------------------------------------------------------------------ perf
    "perf.compression.missing": {
        "client": (
            "Server šalje stranicu nesažetu ({kb} kB). Sažimanje bi prenos smanjilo na otprilike "
            "četvrtinu, što na sporijoj mobilnoj vezi ({speed_mbps} Mb/s) skraćuje učitavanje za oko "
            "{saving_s} s."
        ),
        "tech": "content-encoding={encoding}, html_bytes={bytes} (dekodirano), ušteda ≈ {saving_s} s",
        "variants": {
            "truncated": {
                "client": (
                    "Server šalje stranicu nesažetu (više od {kb} kB). Sažimanje bi prenos smanjilo na "
                    "otprilike četvrtinu, što na sporijoj mobilnoj vezi ({speed_mbps} Mb/s) skraćuje "
                    "učitavanje za više od {saving_s} s."
                ),
                "tech": (
                    "content-encoding={encoding}, html_bytes>{bytes} (dekodirano, sečeno na "
                    "http.max_body_kb), ušteda > {saving_s} s"
                ),
            }
        },
    },
    "perf.redirect.chain": {
        "client": (
            "Otvaranje početne strane prolazi kroz {hops} preusmerenja pre nego što se nešto "
            "prikaže. Svako od njih dodaje čekanje, najviše na mobilnoj vezi."
        ),
        "tech": "redirect_chain={hops} skokova: {chain:join: → }",
    },
    "perf.html.size": {
        "client": (
            "Sam kod početne strane teži {kb} kB, pre slika i skripti. Pretraživač mora sve to "
            "da preuzme i obradi, što usporava prikaz, najviše na telefonu."
        ),
        "tech": "html_bytes={bytes} > {threshold_kb} kB",
        "variants": {
            "truncated": {
                "client": (
                    "Sam kod početne strane teži više od {kb} kB, pre slika i skripti. Pretraživač mora "
                    "sve to da preuzme i obradi, što usporava prikaz, najviše na telefonu."
                ),
                "tech": "html_bytes>{bytes} (sečeno na http.max_body_kb) > {threshold_kb} kB",
            }
        },
    },
    "perf.page.weight": {
        "client": "Početna strana prenosi {mb} MB. " + _WEIGHT,
        "tech": (
            "bytes_at_load={bytes}, bez videa {mb} MB, video {video_mb} MB, zahteva={requests}, "
            "nemereno={unmeasured}, reached={reached}; sa onim posle load {total_bytes} B i "
            "{total_requests} zahteva (informativno)"
        ),
        "variants": {
            "video": {"client": "Početna strana prenosi {mb} MB (video dodatno {video_mb} MB). " + _WEIGHT}
        },
    },
    "perf.request.count": {
        "client": (
            "Otvaranje početne strane pokreće "
            "{requests:n:odvojeno preuzimanje|odvojena preuzimanja|odvojenih preuzimanja}. Svako ima "
            "svoju režiju, što se najviše oseti na mobilnoj vezi."
        ),
        "tech": "requests_at_load={requests}, sa onim posle load {total_requests} (reached={reached})",
    },
    "perf.load.time": {
        "client": (
            "Na simuliranoj vezi od {speed_mbps} Mb/s početnoj strani treba {seconds} s da se do kraja "
            "učita."
        ),
        "tech": "load_ms={load_ms}, reached={reached}",
        "variants": {
            "timeout": {
                "client": (
                    "Na simuliranoj vezi od {speed_mbps} Mb/s početna strana se ni za {seconds} s nije "
                    "do kraja učitala."
                )
            }
        },
    },
    "perf.img.oversized": {
        "client": (
            "Sajt šalje slike znatno veće nego što se prikazuju — oko {kb} kB nepotrebnog prenosa "
            "pri prvoj poseti."
        ),
        "tech": (
            "{image_count} slika sa ratio > {ratio_threshold}, procenjen višak {kb} kB, "
            "nemereno {unmeasured}"
        ),
    },
    "qa.console.errors": {
        "client": (
            "Pri otvaranju početne strane Chrome prijavljuje {errors:n:grešku|greške|grešaka} (delovi "
            "strane koji se nisu učitali ili greške u skriptama). Deo stranice zato možda ne radi kako treba."
        ),
        "tech": "console errors={errors}, warnings={warnings}",
    },
    # ------------------------------------------------------------------- seo
    "seo.canonical.missing": {
        "client": (
            "Početna strana ne govori Google-u koja joj je zvanična adresa. Kad isti sadržaj "
            "postoji na više adresa (sa www i bez, sa parametrima iz reklama), Google sam bira "
            "koju će prikazati — i ume da izabere pogrešnu."
        ),
        "tech": "{page}: nedostaje <link rel=canonical>",
    },
    "seo.canonical.duplicate": {
        "client": (
            "{page_count} od {total:n:proverene stranice|proverene stranice|proverenih stranica} sajta "
            "prijavljuje Google-u drugu adresu kao zvaničnu ({canonical}). Google ih zato može smatrati "
            "kopijama te adrese i izostaviti iz pretrage."
        ),
        "tech": (
            "canonical_normalized == {canonical} na {page_count} od {total} stranica (udeo {share}) "
            "iz {path_groups} grupa putanja (uzorak: {sample})"
        ),
    },
    "seo.title.missing": {
        "client": (
            "Početna strana nema naslov. U kartici pretraživača zato stoji goli deo adrese, a "
            "Google u rezultatima sam smišlja naslov iz sadržaja strane."
        ),
        "tech": "{page}: <title> prazan ili nedostaje (dužina {title_length})",
    },
    "seo.title.duplicate": {
        "client": (
            "Različite stranice sajta imaju isti naslov („{title}”), njih {page_count}. Naslov tako ni "
            "Google-u ni posetiocu ne govori po čemu se te stranice razlikuju."
        ),
        "tech": "identičan normalizovan <title> na {page_count} stranica iz {path_groups} grupa putanja",
    },
    "seo.description.missing": {
        "client": (
            "Početna strana nema kratak opis za Google. Google tada sam bira tekst sa strane za "
            "prikaz ispod naslova, a to ume da bude deo menija ili obaveštenja o kolačićima."
        ),
        "tech": "{page}: nedostaje <meta name=description> (dužina {description_length})",
    },
    "seo.description.duplicate": {
        "client": (
            "Različite stranice sajta imaju isti kratak opis za Google, njih {page_count}. Opis tako ni "
            "Google-u ni posetiocu iz pretrage ne govori po čemu se te stranice razlikuju."
        ),
        "tech": "identičan normalizovan meta opis na {page_count} stranica iz {path_groups} grupa putanja",
    },
    "seo.h1.missing": {
        "client": (
            "Početna strana nema glavni naslov (h1). Naslovi su jedan od signala po kojima Google "
            "razume o čemu je strana, a korisnici čitača ekrana se po njima kreću kroz stranicu."
        ),
        "tech": "h1_count == {h1_count} (mereno u browseru, reached={reached})",
    },
    "seo.h1.multiple": {
        "client": (
            "Početna strana ima {h1_count:n:glavni naslov|glavna naslova|glavnih naslova} (h1) umesto "
            "jednog. Korisnicima čitača ekrana je tada teže da prepoznaju glavnu temu strane."
        ),
        "tech": "h1_count == {h1_count} > {threshold}",
    },
    # ---------------------------------------------------------------- social
    "social.og.title.missing": {
        "client": (
            "Kada neko podeli link sajta u poruci ili na Facebook-u, nema pripremljenog naslova "
            "za pregled linka, pa platforme uzimaju običan naslov strane ili samu adresu."
        ),
        "tech": "{page}: nedostaje og:title (ukupno og oznaka: {og_tag_count})",
    },
    "social.og.description.missing": {
        "client": (
            "Kad se link sajta podeli, platforme nemaju pripremljen opis, pa same biraju tekst sa "
            "strane ili ne prikazuju nijedan."
        ),
        "tech": "{page}: nedostaje og:description (ukupno og oznaka: {og_tag_count})",
    },
    "social.og.image.missing": {
        "client": (
            "Podeljen link sajta nema pripremljenu sliku, pa platforme same biraju sliku sa strane "
            "ili je ne prikazuju."
        ),
        "tech": "{page}: nedostaje og:image (ukupno og oznaka: {og_tag_count})",
    },
    # ------------------------------------------------------------------ i18n
    "i18n.lang.missing": {
        "client": (
            "Početna strana u kodu nema oznaku jezika (lang). Čitači ekrana, koje koriste slepi i "
            "slabovidi posetioci, zato ne znaju kojim izgovorom da je čitaju."
        ),
        "tech": "{page}: <html> bez lang atributa (izvor: {source})",
    },
    "i18n.lang.invalid": {
        "client": (
            "Sajt je u kodu označen oznakom „{lang}”, koja nije ispravna oznaka nijednog jezika. "
            "Čitači ekrana zato ne mogu da se oslone na nju."
        ),
        "tech": '{page}: lang="{lang}" nije upotrebljiv BCP-47 kod (izvor: {source})',
    },
    "i18n.lang.mismatch": {
        "client": (
            "Sadržaj sajta je na srpskom, ali je u kodu označen kao „{lang}”. Čitači ekrana, koje "
            "koriste slepi i slabovidi posetioci, zato srpski tekst izgovaraju po pravilima tog "
            "jezika, pa je teško razumljiv."
        ),
        "tech": (
            '{page}: lang="{lang}", sadržaj prepoznat kao {detected_language} '
            "(ćirilica {cyrillic_share}, dijakritici {diacritic_share}, {text_length} znakova; "
            "izvor: {source})"
        ),
    },
    # ----------------------------------------------------------------- infra
    "infra.sitemap.missing": {
        "client": (
            "Sajt nema mapu stranica (sitemap). Google zato nove i dublje stranice pronalazi samo "
            "preko linkova, sporije, a stranice do kojih ne vodi nijedan link može i da ne pronađe."
        ),
        "tech": "sitemap status={status}, urls={url_count}",
    },
    "infra.robots.missing": {
        "client": (
            "Sajt nema robots.txt. Ništa se time ne lomi, ali Google taj fajl čita pre nego što obiđe "
            "sajt, i njegov izostanak je znak da se sajt nije podešavao za pretragu."
        ),
        "tech": "robots.txt status={status}",
    },
    "infra.soft404": {
        "client": (
            "Na nepostojeću adresu sajt odgovara kao da stranica postoji — obe proverene "
            "izmišljene adrese otvorile su stranicu sa statusom {status}. Pretraživači zato teže "
            "razlikuju prave stranice od nepostojećih i troše obilazak sajta na prazne adrese."
        ),
        "tech": "obe sonde status={status}, sličnost sa početnom {similarity}",
    },
    "infra.tls.invalid": {
        "client": (
            "Sertifikat sajta nije valjan, pa pretraživač posetiocima prikazuje upozorenje pre nego "
            "što uđu na sajt."
        ),
        "tech": "TLS greška: {error}",
    },
    "infra.https.redirect.missing": {
        "client": (
            "Sajt se otvara i na nezaštićenoj adresi {http_url}, bez preusmerenja na {https_url}. "
            "Chrome takvu stranicu označava sa „Nije bezbedno”."
        ),
        "tech": (
            "{http_url} → {status} bez preusmerenja na https; {https_url} → 200 sa ispravnim "
            "sertifikatom"
        ),
    },
    "infra.host.duplicate": {
        "client": (
            "Isti sajt se otvara na {host_count:n:adresi|adrese|adresa} ({hosts:join:, }), a nijedna ne "
            "preusmerava na drugu. Google ih zato vidi kao različite adrese sa istim sadržajem i sam bira "
            "koju da prikaže u pretrazi."
        ),
        "tech": "200 bez preusmerenja na: {hosts:join:, }; isti canonical na svima: {same_canonical}",
        "variants": {
            "same_canonical": {
                "client": (
                    "Isti sajt se otvara na {host_count:n:adresi|adrese|adresa} ({hosts:join:, }), a "
                    "nijedna ne preusmerava na drugu. Oznaka canonical na svima upućuje na istu adresu, "
                    "pa Google zna koju da prikaže, ali preusmerenje nije podešeno."
                )
            }
        },
    },
    "infra.unreachable": {
        "client": (
            "Sajt se nije otvorio ni u jednom od {attempt_count} pokušaja ({first_attempt:utc} i "
            "{second_attempt:utc} UTC): {cause}."
        ),
        "tech": "pokušaji {first_attempt} i {second_attempt}, poslednja greška: {detail}",
    },
    # ------------------------------------------------------------------ a11y
    "a11y.img.alt.missing": {
        "client": (
            "Na početnoj strani {without_alt} od {total:n:slike|slike|slika} nema tekstualni opis "
            "(alt). Posetioci koji koriste čitače ekrana ne saznaju šta je na njima, a Google ima "
            "manje podataka za pretragu slika."
        ),
        "tech": (
            "images_without_alt_attr={without_alt}/{total} (udeo {share}), "
            "images_empty_alt={empty_alt} se namerno ne broji, nemereno={unmeasured}"
        ),
    },
}

# Labels in the HTML report and the email draft. Keys ending in `_html` may contain markup.
TEXT: dict[str, str] = {
    "page_title": "SiteTriage — izveštaj",
    "heading": "SiteTriage — izveštaj",
    "run_of": "Prolaz od {generated} · verzija alata {version}",
    "run_profile": "profil {profile}",
    "run_no_profile": "bez profila",
    "card_domains": "Domena",
    "card_scanned": "Skenirano",
    "card_partial": "Delimično",
    "card_failed": "Neuspešno",
    "card_unreachable": "Ne rade",
    "card_level2": "Na nivou 2",
    "card_excluded": "Izuzeto na zahtev",
    "card_duration": "Trajanje",
    "ranked": "Rangirani domeni",
    "ranked_note": (
        "Redosled je po najtežem pojedinačnom nalazu, pa tek onda po zbiru: sajt sa\n"
        "jednom katastrofom je bolji lead od sajta sa deset sitnica."
    ),
    "col_domain": "Domen",
    "col_industry": "Delatnost",
    "col_score": "Skor",
    "col_worst": "Najteži nalaz",
    "col_findings": "Nalaza",
    "col_level2": "Nivo 2",
    "col_status": "Stanje",
    "yes": "da",
    "no": "ne",
    "by_domain": "Po domenu",
    "unreachable": "Ne rade",
    "unreachable_note": (
        "Sajtovi koji se nisu otvorili ni u drugom pokušaju. Nisu u rangiranju, a predlog teksta\n"
        "za njih je poseban."
    ),
    "not_scanned": "Nije skenirano",
    "not_scanned_note": (
        "Sajtovi koje alat nije pregledao. Možda rade, pa nisu ni u rangiranju ni u „Ne rade”."
    ),
    "excluded_count": "Izuzeto na zahtev administratora: {count}",
    "col_reason": "Razlog",
    "col_check": "Provera",
    "col_share": "Udeo",
    "percent": "{share} %",
    "share_budget": "Potrošen budžet: {share} % domena koji rade",
    "share_unknown": "Nije moglo da se proveri, po proveri (udeo domena koji rade)",
    "assumption_html": (
        "<b>Pretpostavka za procenu vremena učitavanja:</b> efektivna brzina\n"
        "{speed} Mb/s ({mb_per_s} MB/s, spora 4G veza) uz {overhead} s režijskog\n"
        "vremena. Broj koji šalješ klijentu moraš umeti da odbraniš, a broj bez navedene pretpostavke\n"
        "ne možeš."
    ),
    "read_only_html": (
        "Alat čita, nikad ne piše. Ne skenira portove, ne pokušava prijavu i ne traži ranjivosti.\n"
        "Osim početne strane i dve izmišljene adrese za proveru greške 404, ne otvara stranice koje\n"
        "<code>robots.txt</code> zabranjuje."
    ),
    "summary_meta": (
        "{industry} · skor {score} ·\nnajteži {worst} · {findings:n:nalaz|nalaza|nalaza}"
    ),
    "copy_draft": "Kopiraj predlog teksta",
    "copied": "Kopirano ✓",
    "no_findings": "Nijedan nalaz — sajt je na proverenim tačkama uredan.",
    "unknowns": "Nije moglo da se proveri ({count})",
    "not_applicable": "ne primenjuje se: {text}",
    "escalated_because": "Na nivo 2 poslat jer: ",
    "finding_meta": "· nivo {level} · bodovi: {weight}",
    "draft_clean": "Na sajtu {domain} nisam našao značajnije probleme.",
    "draft_opening": "Poštovani,\n\npregledao sam sajt {domain} i primetio sledeće:\n\n",
    "draft_closing": (
        "\n\nAko vas zanima, mogu da pošaljem detaljan pregled sa predlogom šta prvo popraviti.\n"
    ),
    "draft_unreachable": (
        "Poštovani,\n\npišem u vezi sa sajtom {domain}. {sentence}\n\n"
        "Ako vam je potrebna pomoć oko sajta, rado ću pomoći.\n"
    ),
    "severity_critical": "KRITIČNO",
    "severity_high": "VISOKO",
    "severity_medium": "SREDNJE",
    "severity_low": "NISKO",
}

# Reasons: why something was not checked (`unknown`) and why a domain goes to level 2. The
# operator reads them, not the client, so they are technical.
REASONS: dict[str, str] = {
    "requires.entry": "početna strana nije zabeležena (dohvatanje je puklo, vidi log)",
    "requires.entry_response": "početna nije vratila nijedan odgovor (mrežna greška pre HTTP-a)",
    "requires.home": "početna strana nije uspešno dohvaćena",
    "requires.home_html": "sirovi HTML početne strane nije sačuvan",
    "requires.home_complete": (
        "HTML početne je veći od http.max_body_kb i tu je sečen, pa ono što je posle granice nije viđeno"
    ),
    "body_truncated": "HTML početne je sečen na {kb} kB (http.max_body_kb), pa se ne zna koliko je ceo",
    "sitemap_too_large": (
        "mapa sajta je veća od granice (sitemap.max_kb ili http.max_body_kb) i nije pročitana, pa se ne "
        "zna da li navodi adrese"
    ),
    "requires.robots": "zahtev za robots.txt nije izvršen (mrežna greška ili budžet)",
    "requires.sitemap": "zahtev za sitemap nije izvršen (mrežna greška ili budžet)",
    "requires.soft404": "bar jedna od dve sonde za lažni 404 nije izvršena",
    "requires.browser": "stranica nije otvorena u browseru",
    "requires.network": "mrežni saobraćaj nije izmeren",
    "v1_snapshot": "snapshot iz verzije {version} nema {field}",
    "check_crashed": "provera je pukla: {error}",
    "sitemap_status": "server je na sitemap odgovorio statusom {status}; iz toga se ne vidi da li postoji",
    "robots_status": "server je na robots.txt odgovorio statusom {status}; iz toga se ne vidi da li postoji",
    "probe_status": (
        "sonde su dobile status {statuses:join:, }; iz toga se ne vidi kako sajt odgovara na "
        "nepostojeću adresu"
    ),
    "tls_no_connection": "veza nije uspostavljena ({kind}), sertifikat nije proveren",
    "tls_incomplete_chain": (
        "server ne šalje ceo lanac sertifikata; browser ume sam da dopuni lanac, pa se ne zna da li "
        "posetilac vidi upozorenje"
    ),
    "tls_over_http": (
        "https nije uspeo ({kind}: {detail}); sajt je dohvaćen preko http-a, sertifikat nije proveren"
    ),
    "unmeasured_responses": "{unmeasured} odgovora nije izmereno (prag {threshold})",
    "load_incomplete": "učitavanje prekinuto pre kraja, izmereno je nepotpuno",
    "load_not_measured": "vreme učitavanja nije izmereno",
    "images_unmeasured": "{unmeasured} od {total:n:slike|slike|slika} nije izmereno",
    "oversized_unmeasured": (
        "{count:n:prevelika slika nema|prevelike slike nemaju|prevelikih slika nema} izmeren prenos, "
        "pa višak nije poznat"
    ),
    "h1_timeout": "stranica nije dovršila učitavanje, h1 može da stigne kasnije",
    "images_timeout": "stranica nije dovršila učitavanje, slike nisu prebrojane",
    "text_too_short": "premalo teksta u sirovom HTML-u ({length} < {threshold} znakova)",
    "text_too_short_rendered": (
        "premalo teksta i na stranici posle JavaScript-a ({length} < {threshold} "
        "znakova)"
    ),
    "unreachable_unsure": (
        "početna nije vratila odgovor ({kind}, pokušaja: {attempts}); iz toga se ne vidi da sajt ne radi"
    ),
    # duplicate checks when the sample has fewer pages than the threshold (ADR-015)
    "pages_budget": (
        "uzorak ima manje od {threshold:n:stranice|stranice|stranica}, jer je budžet potrošen pre kraja"
    ),
    "pages_sample": (
        "uzorak ima manje od {threshold:n:stranice|stranice|stranica}, a sajt ima bar "
        "{address_count:n:internu adresu|interne adrese|internih adresa}"
    ),
    "pages_js": (
        "uzorak ima manje od {threshold:n:stranice|stranice|stranica}, a veze koje crta JavaScript nisu "
        "viđene (nivo 2 nije radio, a sirovi HTML početne je prazan ili bez h1)"
    ),
    # i18n.lang.mismatch without a content-language profile (ADR-023)
    "no_content_language": (
        "prepoznavanje jezika sadržaja je isključeno, jer ga nijedan profil ne uključuje "
        "(na primer --profile rs)"
    ),
    "few_pages": (
        "sajt ima {address_count:n:internu adresu|interne adrese|internih adresa}, a za "
        "poređenje treba bar {threshold}"
    ),
    # host variants: http/https × www/without www (ADR-014)
    "requires.host_variants": "varijante adrese (http/https, sa i bez www) nisu dohvaćene u ovom snimku",
    "variant_unchecked": "{url} nije viđena kao u pretraživaču ({kind}), pa se ne zna da li služi sajt",
    "no_https": "https na {url} ne vraća stranicu, pa nema na šta da se preusmerava",
    # light level 2 for sites over the limit (BUG-020)
    "requires.level2_full": (
        "sajt je meren lagano, bez mrežnog profila, jer nije bio među sajtovima izabranim za pun "
        "nivo 2, pa vreme učitavanja nije mereno"
    ),
    # network profile of level 2 (ADR-010)
    "requires.network_profile": (
        "snimak je napravljen pre mrežnog profila, pa je vreme izmereno bez mrežnog profila, na stvarnoj vezi"
    ),
    # real connection measured before level 2 (ADR-018)
    "requires.link": (
        "stvarna veza nije izmerena pre nivoa 2, pa se ne zna da li je vreme mereno pod profilom"
    ),
    "link_slow": (
        "stvarna veza je bila {measured_mbps} Mb/s, a za merenje pod profilom treba bar "
        "{required_mbps} Mb/s, "
        "pa bi vreme bilo precenjeno"
    ),
    # why a domain was not scanned (the „Nije skenirano" list)
    "entry_missing": "snapshot nema početnu (dohvatanje je puklo, vidi log)",
    "entry_status": "početna je vratila status {status}",
    "entry_error": "{kind}: {detail}",
    # escalation to level 2
    "raw_text_short": "sirovi HTML ima {chars:n:znak|znaka|znakova} teksta (< {threshold})",
    "no_h1_raw": "sirovi HTML nema nijedan h1 — nivo 2 proverava da li ga crta JavaScript",
    "medium_finding": "ima bar jedan nalaz nivoa 1 ozbiljnosti ≥ medium",
    "html_large": "HTML početne je {bytes} B (> {threshold})",
    "html_uncompressed": "HTML se ne šalje kompresovan",
    "slow_entry": "početna odgovara za {ms} ms (> {threshold})",
    "forced_level2": "izričito traženo preko --level 2",
}
