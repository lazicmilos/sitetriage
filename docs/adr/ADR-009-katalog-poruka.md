# ADR-009: Sentences are built at display time, from a catalog

```
Status:  Accepted
Date:    2026-09-25
Author:  Milos Lazic
```

Originally written in Serbian; translated for v3.

## Context

The client sentence used to be built at check time (`registry.finding` →
`message_template.format`), in Serbian, and stored in the finding. The evidence already contained
inflected Serbian phrases ("3 kopije", "(video dodatno 8 MB)", "175 odvojenih preuzimanja", that is
"3 copies", "(plus 8 MB of video)", "175 separate downloads"). Such a finding cannot be shown in
English, a `diff` between two runs would compare text instead of measurements, and an old run could
never get a corrected sentence.

## Decision

- `Finding` carries `check_id`, the evidence and an optional `variant`, not a sentence. The sentence
  is built at display time by `sitetriage.messages.render(finding, lang)`.
- There is one catalog per language (`sitetriage/messages/sr.py`, `en.py`). It holds the client and
  the technical sentence for every check, the labels of the HTML report, the draft email and the
  names of the technical codes that appear in the evidence.
- A template is plain `str.format` with two additions: `{count:n:form|form|form}` for a number with
  its noun (three forms in Serbian, two in English) and `{list:join: → }`. A decimal number in a
  client sentence is written the way the language writes it; the technical sentence leaves it as it
  is.
- Evidence contains only numbers, booleans, URLs, technical codes, raw error messages and text taken
  from the site (title, description). A test allows a value with spaces only under those keys.
- A check with more than one sentence form picks the form through `variant`, for example weight
  with and without video.
- Before the change a golden file was made (`tests/golden/messages-sr.json`): 92 Serbian sentences for
  all 28 checks, from the test set and from the cases that change the form of a sentence. After the
  change the catalog produces the same sentences.

## Consequences

- `--lang sr|en` applies to `scan`, `recheck` and the reports, and `sitetriage explain` prints both
  languages.
- A new check needs an entry in both catalogs; a test fails if one is missing or if a language has
  an extra one.
- The English sentence must not claim more than the Serbian one. The same tests apply to both
  languages, and the owner reviews the English version.
- Reasons for `unknown` and reasons for escalation are also code plus data (`Reason`), and the
  sentence is built by `sitetriage.messages.reason` (owner decision of 2026-09-25). The golden file
  `tests/golden/reasons-sr.json` keeps the Serbian sentences as they were before the change.
- The evidence changed: the inflected phrases are gone, `sample` is a code (`sitemap`, `links`),
  a missing encoding is `null`, and the redirect chain is a list. This is a breaking change and is
  recorded in the CHANGELOG.
