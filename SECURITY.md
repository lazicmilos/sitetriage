# Security policy

## Supported versions

Security fixes go into the latest release line only. Older lines do not get backports.

| Version | Supported |
|---|---|
| 2.x (latest) | yes |
| < 2.0 | no |

## Reporting a vulnerability

Please do **not** open a public issue, discussion or pull request for a vulnerability.

Report it privately through GitHub: open the repository's **Security** tab and choose **Report a
vulnerability** (GitHub private vulnerability reporting). Only the maintainer can see the report.

Please include:

- the version (`skener --version`) and how you run it (Docker image, `pip install`, web app on top of
  the library);
- what an attacker controls (the domain list, a scanned site's responses, DNS, the config file);
- steps or a minimal reproduction, for example a small local server or a snapshot, without real
  client domains;
- the impact you expect.

The project is maintained by one person. You can expect an acknowledgement within a week. We will
agree with you on a disclosure date, normally once a fixed release is out, and credit you in the
advisory unless you prefer otherwise.

## Scope

SiteTriage reads websites it does not control and is meant to run behind a web application, so
everything a scanned site or a user-supplied domain can influence is in scope. In particular:

- **SSRF protections** ([ADR-006](docs/adr/ADR-006-ssrf.md)). Any way to make the tool connect to a
  private, loopback, link-local or otherwise non-global address (for example `localhost`, `10.x`,
  `169.254.169.254`, IPv4-mapped IPv6) at level 1: through DNS, DNS rebinding, redirects, an IP
  address, port or user name in the domain, proxy environment variables, or a bypass of
  `[net] allowed_private`. At level 2, any request that the browser's request filter should block and
  does not, beyond the limits listed below.
- **Politeness guarantees.** Any way a scanned site or input can make the tool break its own limits:
  more than one concurrent request to the same site (including `www` and bare host variants), skipping
  the pause between requests or `Crawl-delay`, fetching a path disallowed by `robots.txt`, exceeding
  the per-domain request or time budget, retrying after `429`/`503`, sending requests without the
  operator identity, or requesting an excluded domain.
- **Parsing untrusted content.** HTML, `robots.txt`, XML sitemaps (including gzip-compressed ones and
  sitemap indexes), HTTP headers and CSV input. Crashes that abort a whole run, resource exhaustion
  (memory, CPU, decompression or XML expansion bombs) and limits that can be bypassed are in scope.
- **The generated report.** `index.html` contains text taken from scanned sites (titles,
  descriptions, URLs, console errors). Any way to inject script or markup into the report (XSS),
  and any way to inject formulas or break rows in `findings.csv` and `summary.csv`, is in scope. The
  same goes for `report.json` content that makes a consumer following the schema misbehave.
- **Files on disk.** Path traversal or overwrites through domain names, snapshot paths or report
  output.

## Out of scope

- Vulnerabilities in Chromium itself, or in Playwright's browser builds. Report those upstream to the
  [Chromium project](https://www.chromium.org/Home/chromium-security/reporting-security-bugs/). If the
  tool's own configuration of Chromium makes such a bug reachable or worse, that part is in scope.
- **The known level 2 limitations in ADR-006.** At level 2, Playwright's request routing does not see
  redirect targets or WebSocket connections, and Chromium resolves names itself, so there is a window
  between our check and its connection. These are documented and accepted. Level 2 is the first line
  of defence, not the only one: **a production deployment must filter outbound network traffic**
  (egress) so the scanning process can only reach public addresses. Reports that show a way around
  that egress requirement, or a new gap not in the list, are in scope.
- Deliberate configuration by the operator, such as adding hosts to `[net] allowed_private` or
  pointing `SKENER_CHROMIUM` at a different browser.
- Findings that are wrong or missed. Those are bugs, not vulnerabilities: use the "Wrong or missed
  finding" issue template.
