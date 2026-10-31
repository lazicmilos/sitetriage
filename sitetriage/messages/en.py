"""English catalog. Each sentence claims exactly what the Serbian one claims, no more and no less.

Pregleda ga vlasnik po tri pravila iz IT-SKENER-002 §3.3: tvrdnja mora da se proveri, svaki
broj mora da potiče iz dokaza, a broj i imenica moraju da se slažu.
"""

from __future__ import annotations


def decimal(number: float) -> str:
    """„14.9", „22", „0.1" — no trailing „.0"."""
    return f"{number:.1f}".removesuffix(".0")


def plural(number: int, forms: list[str]) -> str:
    singular, many = forms
    return singular if number == 1 else many


DECIMAL = decimal

CODES: dict[str, dict[object, str]] = {
    "encoding": {None: "none"},
    "error": {"unknown": "unknown"},
    "kind": {None: "unknown", "dns_temporary": "DNS temporarily unavailable", "blocked": "SSRF protection"},
    "sample": {"sitemap": "sitemap", "links": "internal links from the home page", "none": "home page only"},
    "source": {"raw_html": "raw HTML", "rendered": "the page after JavaScript"},
    "cause": {
        "dns": "the domain has no record that connects it to a server",
        "no_response": "the server accepted a connection over neither https nor http",
    },
}

_WEIGHT = (
    "On a slower mobile connection ({speed_mbps} Mb/s) that takes about {seconds} s."
)

FINDINGS: dict[str, dict] = {
    # ------------------------------------------------------------------ perf
    "perf.compression.missing": {
        "client": (
            "The server sends the page uncompressed ({kb} kB). Compression would cut the transfer to "
            "roughly a quarter, which on a slower mobile connection ({speed_mbps} Mb/s) shortens loading "
            "by about {saving_s} s."
        ),
        "tech": "content-encoding={encoding}, html_bytes={bytes} (decoded), saving ≈ {saving_s} s",
    },
    "perf.redirect.chain": {
        "client": (
            "Opening the home page goes through {hops:n:redirect|redirects} before anything is "
            "shown. Each of them adds waiting time, especially on a mobile connection."
        ),
        "tech": "redirect_chain={hops} hops: {chain:join: → }",
    },
    "perf.html.size": {
        "client": (
            "The home page code alone weighs {kb} kB, before images and scripts. The browser has to "
            "download and process it in full, which slows down rendering, especially on a phone."
        ),
        "tech": "html_bytes={bytes} > {threshold_kb} kB",
    },
    "perf.page.weight": {
        "client": "The home page transfers {mb} MB. " + _WEIGHT,
        "tech": (
            "bytes_at_load={bytes}, without video {mb} MB, video {video_mb} MB, requests={requests}, "
            "unmeasured={unmeasured}, reached={reached}; including what came after load {total_bytes} B "
            "and {total_requests} requests (informational)"
        ),
        "variants": {
            "video": {"client": "The home page transfers {mb} MB (plus {video_mb} MB of video). " + _WEIGHT}
        },
    },
    "perf.request.count": {
        "client": (
            "Opening the home page starts {requests:n:separate download|separate downloads}. Each one "
            "carries its own overhead, which is felt especially on a mobile connection."
        ),
        "tech": (
            "requests_at_load={requests}, {total_requests} including those after load "
            "(reached={reached})"
        ),
    },
    "perf.load.time": {
        "client": (
            "On a simulated {speed_mbps} Mb/s connection, the home page needs {seconds} s to load completely."
        ),
        "tech": "load_ms={load_ms}, reached={reached}",
        "variants": {
            "timeout": {
                "client": (
                    "On a simulated {speed_mbps} Mb/s connection, the home page did not finish loading even "
                    "in {seconds} s."
                )
            }
        },
    },
    "perf.img.oversized": {
        "client": (
            "The site sends images much larger than they are displayed — about {kb} kB of unnecessary "
            "transfer on the first visit."
        ),
        "tech": (
            "{image_count} images with ratio > {ratio_threshold}, estimated excess {kb} kB, "
            "unmeasured {unmeasured}"
        ),
    },
    "qa.console.errors": {
        "client": (
            "When the home page opens, Chrome reports {errors:n:error|errors} (parts of the page that "
            "failed to load, or script errors). Part of the page may therefore not work as intended."
        ),
        "tech": "console errors={errors}, warnings={warnings}",
    },
    # ------------------------------------------------------------------- seo
    "seo.canonical.missing": {
        "client": (
            "The home page does not tell Google which address is its official one. When the same "
            "content exists at several addresses (with and without www, with ad parameters), Google "
            "picks which one to show on its own — and it can pick the wrong one."
        ),
        "tech": "{page}: missing <link rel=canonical>",
    },
    "seo.canonical.duplicate": {
        "client": (
            "{page_count} of the {total:n:checked page|checked pages} on the site report a different "
            "address to Google as their official one ({canonical}). Google may therefore treat them as "
            "copies of that address and leave them out of search results."
        ),
        "tech": (
            "canonical_normalized == {canonical} on {page_count} of {total} pages (share {share}) "
            "from {path_groups} path groups (sample: {sample})"
        ),
    },
    "seo.title.missing": {
        "client": (
            "The home page has no title. The browser tab therefore shows a bare part of the address, "
            "and Google makes up a title from the page content in its results."
        ),
        "tech": "{page}: <title> empty or missing (length {title_length})",
    },
    "seo.title.duplicate": {
        "client": (
            "Different pages of the site have the same title (“{title}”), {page_count} of them. So the "
            "title tells neither Google nor a visitor how those pages differ."
        ),
        "tech": "identical normalized <title> on {page_count} pages from {path_groups} path groups",
    },
    "seo.description.missing": {
        "client": (
            "The home page has no short description for Google. Google then picks text from the page "
            "to show below the title, and that can be part of the menu or the cookie notice."
        ),
        "tech": "{page}: missing <meta name=description> (length {description_length})",
    },
    "seo.description.duplicate": {
        "client": (
            "Different pages of the site have the same short description for Google, {page_count} of "
            "them. So the description tells neither Google nor a visitor from search how those pages "
            "differ."
        ),
        "tech": "identical normalized meta description on {page_count} pages from {path_groups} path groups",
    },
    "seo.h1.missing": {
        "client": (
            "The home page has no main heading (h1). Headings are one of the signals Google uses to "
            "understand what a page is about, and screen reader users navigate the page by them."
        ),
        "tech": "h1_count == {h1_count} (measured in the browser, reached={reached})",
    },
    "seo.h1.multiple": {
        "client": (
            "The home page has {h1_count:n:main heading|main headings} (h1) instead of one. Screen reader "
            "users then find it harder to recognize the main topic of the page."
        ),
        "tech": "h1_count == {h1_count} > {threshold}",
    },
    # ---------------------------------------------------------------- social
    "social.og.title.missing": {
        "client": (
            "When someone shares a link to the site in a message or on Facebook, there is no prepared "
            "title for the link preview, so platforms use the plain page title or the address itself."
        ),
        "tech": "{page}: missing og:title (og tags in total: {og_tag_count})",
    },
    "social.og.description.missing": {
        "client": (
            "When a link to the site is shared, platforms have no prepared description, so they pick "
            "text from the page themselves or show no description."
        ),
        "tech": "{page}: missing og:description (og tags in total: {og_tag_count})",
    },
    "social.og.image.missing": {
        "client": (
            "A shared link to the site has no prepared image, so platforms pick an image from the page "
            "themselves or show none."
        ),
        "tech": "{page}: missing og:image (og tags in total: {og_tag_count})",
    },
    # ------------------------------------------------------------------ i18n
    "i18n.lang.missing": {
        "client": (
            "The home page has no language tag (lang) in its code. Screen readers, used by blind and "
            "visually impaired visitors, therefore do not know which pronunciation to read it with."
        ),
        "tech": "{page}: <html> without a lang attribute (source: {source})",
    },
    "i18n.lang.invalid": {
        "client": (
            "The site is marked in its code with “{lang}”, which is not a valid tag for any language. "
            "Screen readers therefore cannot rely on it."
        ),
        "tech": '{page}: lang="{lang}" is not a usable BCP-47 code (source: {source})',
    },
    "i18n.lang.mismatch": {
        "client": (
            "The site content is in Serbian, but its code marks it as “{lang}”. Screen readers, used "
            "by blind and visually impaired visitors, therefore pronounce the Serbian text by the "
            "rules of that language, which makes it hard to understand."
        ),
        "tech": (
            '{page}: lang="{lang}", content detected as {detected_language} '
            "(Cyrillic {cyrillic_share}, diacritics {diacritic_share}, {text_length} characters; "
            "source: {source})"
        ),
    },
    # ----------------------------------------------------------------- infra
    "infra.sitemap.missing": {
        "client": (
            "The site has no page map (sitemap). Google therefore finds new and deeper pages only "
            "through links, more slowly, and may not find pages that no link leads to."
        ),
        "tech": "sitemap status={status}, urls={url_count}",
    },
    "infra.robots.missing": {
        "client": (
            "The site has no robots.txt. Nothing breaks because of it, but Google reads that file "
            "before it crawls the site, and its absence is a sign that the site was not set up for "
            "search."
        ),
        "tech": "robots.txt status={status}",
    },
    "infra.soft404": {
        "client": (
            "For an address that does not exist, the site answers as if the page existed — both "
            "made-up addresses we checked opened a page with status {status}. Search "
            "engines therefore have a harder time telling real pages from nonexistent ones and "
            "spend their crawl of the site on empty addresses."
        ),
        "tech": "both probes status={status}, similarity to the home page {similarity}",
    },
    "infra.tls.invalid": {
        "client": (
            "The site's certificate is not valid, so the browser shows visitors a warning before they "
            "enter the site."
        ),
        "tech": "TLS error: {error}",
    },
    "infra.https.redirect.missing": {
        "client": (
            "The site also opens at the unprotected address {http_url}, without a redirect to "
            "{https_url}. Chrome marks such a page as “Not secure”."
        ),
        "tech": (
            "{http_url} → {status} without a redirect to https; {https_url} → 200 with a valid "
            "certificate"
        ),
    },
    "infra.host.duplicate": {
        "client": (
            "The same site opens at {host_count:n:address|addresses} ({hosts:join:, }), and none of them "
            "redirects to another. Google therefore sees them as different addresses with the same content "
            "and picks by itself which one to show in search."
        ),
        "tech": "200 without a redirect at: {hosts:join:, }; same canonical on each: {same_canonical}",
        "variants": {
            "same_canonical": {
                "client": (
                    "The same site opens at {host_count:n:address|addresses} ({hosts:join:, }), and none "
                    "of them redirects to another. The canonical tag on each of them points to the same "
                    "address, so Google knows which one to show, but no redirect is set up."
                )
            }
        },
    },
    "infra.unreachable": {
        "client": (
            "The site did not open in any of the {attempt_count:n:attempt|attempts} ({first_attempt:utc} and "
            "{second_attempt:utc} UTC): {cause}."
        ),
        "tech": "attempts {first_attempt} and {second_attempt}, last error: {detail}",
    },
    # ------------------------------------------------------------------ a11y
    "a11y.img.alt.missing": {
        "client": (
            "On the home page, {without_alt} of {total:n:image|images} have no text description (alt). "
            "Visitors who use screen readers do not learn what is on them, and Google has less data "
            "for image search."
        ),
        "tech": (
            "images_without_alt_attr={without_alt}/{total} (share {share}), "
            "images_empty_alt={empty_alt} deliberately not counted, unmeasured={unmeasured}"
        ),
    },
}

TEXT: dict[str, str] = {
    "page_title": "SiteTriage — report",
    "heading": "SiteTriage — report",
    "run_of": "Run of {generated} · tool version {version}",
    "card_domains": "Domains",
    "card_scanned": "Scanned",
    "card_partial": "Partial",
    "card_failed": "Failed",
    "card_unreachable": "Not working",
    "card_level2": "On level 2",
    "card_excluded": "Excluded on request",
    "card_duration": "Duration",
    "ranked": "Ranked domains",
    "ranked_note": (
        "The order is by the single worst finding, and only then by the total: a site with\n"
        "one disaster is a better lead than a site with ten small issues."
    ),
    "col_domain": "Domain",
    "col_industry": "Industry",
    "col_score": "Score",
    "col_worst": "Worst finding",
    "col_findings": "Findings",
    "col_level2": "Level 2",
    "col_status": "Status",
    "yes": "yes",
    "no": "no",
    "by_domain": "By domain",
    "unreachable": "Not working",
    "unreachable_note": (
        "Sites that did not open on the second attempt either. They are not ranked, and their suggested\n"
        "text is a separate one."
    ),
    "not_scanned": "Not scanned",
    "not_scanned_note": (
        "Sites the tool did not review. They may work, so they are neither ranked nor “Not working”."
    ),
    "excluded_count": "Excluded at the administrator's request: {count}",
    "col_reason": "Reason",
    "col_check": "Check",
    "col_share": "Share",
    "percent": "{share} %",
    "share_budget": "Budget spent: {share} % of working domains",
    "share_unknown": "Could not be checked, per check (share of working domains)",
    "assumption_html": (
        "<b>Assumption for the loading time estimate:</b> effective speed\n"
        "{speed} Mb/s ({mb_per_s} MB/s, a slow 4G connection) plus {overhead} s of overhead\n"
        "time. A number you send to a client must be one you can defend, and you cannot defend a\n"
        "number without a stated assumption."
    ),
    "read_only_html": (
        "The tool reads, it never writes. It does not scan ports, attempt logins, or look for\n"
        "vulnerabilities. Apart from the home page and two made-up addresses for the 404 check, it\n"
        "does not open pages that <code>robots.txt</code> disallows."
    ),
    "summary_meta": "{industry} · score {score} ·\nworst {worst} · {findings:n:finding|findings}",
    "copy_draft": "Copy suggested text",
    "copied": "Copied ✓",
    "no_findings": "No findings — the site is in order on the checked points.",
    "unknowns": "Could not be checked ({count})",
    "not_applicable": "does not apply: {text}",
    "escalated_because": "Sent to level 2 because: ",
    "finding_meta": "· level {level} · points: {weight}",
    "draft_clean": "I did not find any significant problems on {domain}.",
    "draft_opening": "Hello,\n\nI reviewed the site {domain} and noticed the following:\n\n",
    "draft_closing": (
        "\n\nIf you are interested, I can send a detailed review with a suggestion of what to fix first.\n"
    ),
    "draft_unreachable": (
        "Hello,\n\nI am writing about the site {domain}. {sentence}\n\n"
        "If you need help with the site, I would be glad to help.\n"
    ),
    "severity_critical": "CRITICAL",
    "severity_high": "HIGH",
    "severity_medium": "MEDIUM",
    "severity_low": "LOW",
}

REASONS: dict[str, str] = {
    "requires.entry": "the home page was not recorded (fetching crashed, see the log)",
    "requires.entry_response": "the home page returned no response (network error before HTTP)",
    "requires.home": "the home page was not fetched successfully",
    "requires.home_html": "the raw HTML of the home page was not saved",
    "requires.robots": "the robots.txt request did not complete (network error or budget)",
    "requires.sitemap": "the sitemap request did not complete (network error or budget)",
    "requires.soft404": "at least one of the two soft 404 probes did not complete",
    "requires.browser": "the page was not opened in the browser",
    "requires.network": "network traffic was not measured",
    "v1_snapshot": "a snapshot from version {version} has no {field}",
    "check_crashed": "the check crashed: {error}",
    "sitemap_status": (
        "the server answered the sitemap request with status {status}; that does not show whether it exists"
    ),
    "robots_status": (
        "the server answered the robots.txt request with status {status}; that does not show whether it "
        "exists"
    ),
    "probe_status": (
        "the probes got status {statuses:join:, }; that does not show how the site answers a nonexistent "
        "address"
    ),
    "tls_no_connection": "no connection was established ({kind}), the certificate was not checked",
    "tls_incomplete_chain": (
        "the server does not send the full certificate chain; a browser can complete the chain on its "
        "own, so it is unknown whether visitors see a warning"
    ),
    "tls_over_http": (
        "https failed ({kind}: {detail}); the site was fetched over http, the certificate was not checked"
    ),
    "unmeasured_responses": "{unmeasured} responses were not measured (threshold {threshold})",
    "load_incomplete": "loading was cut off before the end, the measurement is incomplete",
    "load_not_measured": "the loading time was not measured",
    "images_unmeasured": "{unmeasured} of {total} images were not measured",
    "oversized_unmeasured": (
        "{count:n:oversized image has|oversized images have} no measured transfer, so the waste is unknown"
    ),
    "h1_timeout": "the page did not finish loading, the h1 may arrive later",
    "images_timeout": "the page did not finish loading, the images were not counted",
    "text_too_short": "too little text in the raw HTML ({length} < {threshold} characters)",
    "text_too_short_rendered": (
        "too little text even on the page after JavaScript ({length} < {threshold} characters)"
    ),
    "unreachable_unsure": (
        "the home page returned no response ({kind}, attempts: {attempts}); that does not show that the "
        "site is down"
    ),
    # duplicate checks when the sample has fewer pages than the threshold (Z-21)
    "pages_budget": (
        "the sample has fewer than {threshold:n:page|pages}, because the budget ran out before the end"
    ),
    "pages_sample": (
        "the sample has fewer than {threshold:n:page|pages}, but the site has at least "
        "{address_count:n:internal address|internal addresses}"
    ),
    "pages_js": (
        "the sample has fewer than {threshold:n:page|pages}, and links drawn by JavaScript were not seen "
        "(level 2 did not run, and the raw HTML of the home page is empty or has no h1)"
    ),
    "few_pages": (
        "the site has {address_count:n:internal address|internal addresses}, and a comparison "
        "needs at least {threshold}"
    ),
    # host variants: http/https × www/without www (Z-26)
    "requires.host_variants": (
        "the address variants (http/https, with and without www) were not fetched in this snapshot"
    ),
    # light level 2 for sites over the limit (BUG-020)
    "requires.level2_full": (
        "the site was measured lightly, without the network profile, because it was not among the sites "
        "chosen for full level 2, so the load time was not measured"
    ),
    # network profile of level 2 (Z-30)
    "requires.network_profile": (
        "the snapshot predates the network profile, so the load time was measured on the real connection"
    ),
    # real connection before level 2 (Z-33)
    "requires.link": (
        "the real connection was not measured before level 2, so it is unknown whether the time was measured "
        "under the profile"
    ),
    "link_slow": (
        "the real connection was {measured_mbps} Mb/s, and measuring under the profile needs at least "
        "{required_mbps} Mb/s, so the time would be overstated"
    ),
    "variant_unchecked": (
        "{url} was not seen the way a browser sees it ({kind}), so it is unknown whether it serves "
        "the site"
    ),
    "no_https": "https on {url} does not return a page, so there is nothing to redirect to",
    # why a domain was not scanned (the „Not scanned" list)
    "entry_missing": "the snapshot has no home page (fetching crashed, see the log)",
    "entry_status": "the home page returned status {status}",
    "entry_error": "{kind}: {detail}",
    # escalation to level 2
    "raw_text_short": "the raw HTML has {chars} characters of text (< {threshold})",
    "no_h1_raw": "the raw HTML has no h1 — level 2 checks whether JavaScript draws it",
    "medium_finding": "there is at least one level 1 finding of severity ≥ medium",
    "html_large": "the home page HTML is {bytes} B (> {threshold})",
    "html_uncompressed": "the HTML is not sent compressed",
    "slow_entry": "the home page responds in {ms} ms (> {threshold})",
    "forced_level2": "explicitly requested with --level 2",
}
