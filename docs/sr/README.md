# Serbian historical documents

SiteTriage was developed in Serbian until version 3.0. The documents in this folder are the record
of how versions 1 and 2 were tested and calibrated. They are kept as they were written, in Serbian,
and are not maintained any more. Current decisions live in the
[architecture decision records](../adr/README.md), and current procedures in the
[docs index](../README.md).

| File | Id | What it is |
|---|---|---|
| [plan-testiranja.md](plan-testiranja.md) | PT-SKENER-001 | Test plan: strategy, the two calibration lists, exit criteria for v1 and v2, test risks and defect management. |
| [izvestaj-testiranja-100.md](izvestaj-testiranja-100.md) | IT-SKENER-001 | Test report of the first system test over 100 real domains (list A), with the first defects (BUG-001 onward) and observations. |
| [izvestaj-testiranja-2.md](izvestaj-testiranja-2.md) | IT-SKENER-002 | Test report of the fix cycle and the repeated run over the same 100 domains, the review of client sentences and mutation testing. Basis of release 1.0.0. |
| [izvestaj-testiranja-3.md](izvestaj-testiranja-3.md) | IT-SKENER-003 | Test report of v2: calibration on list A, validation on list B, the manual check and the owner decisions. Basis of release 2.0.0. |
| [kalibracija.md](kalibracija.md) | | Calibration log: every run over real sites and every threshold decision, newest first, in the form observation, cause, decision. |
| [kvalitet.md](kvalitet.md) | | Review of the tool against the eight characteristics of ISO/IEC 25010, with the test or module that backs each claim and the known gaps. |

List A and list B are two private lists of 100 real websites each, mostly small businesses and
associations in Serbia: list A for calibrating thresholds, list B, with no overlap, for validating
them. Neither list is published, and
the documents name no domains from them.

The documents cite specification sections (`§4.2`), v2 requirements (`Z-26`), bugs (`BUG-020`),
observations (`O-7`) and document ids (`IT-SKENER-003`). The sources behind most of these ids were
never published. [legacy-references.md](../adr/legacy-references.md) decodes each id and says where
it is documented now.

The relative links inside these files were updated when they moved here. Everything else is
unchanged, including paths in the text such as `skener/` and `skener.toml`, which are the names
from before version 3.0 ([ADR-012](../adr/ADR-012-english-public-interface.md)).
