# Dependency security

## Locked environments

Runtime, catalog and development dependencies remain pinned in their existing locks. Development uses `uv==0.11.15`, correcting the reported entry-point write and RECORD deletion issues ([write advisory](https://github.com/astral-sh/uv/security/advisories/GHSA-4gg8-gxpx-9rph), [deletion advisory](https://github.com/astral-sh/uv/security/advisories/GHSA-pjjw-68hj-v9mw)). Regeneration preserved runtime/catalog pins; only the development uv pin changed.

`requirements/security.in` and its generated `security.txt` isolate `pip-audit==2.10.1` and its dependencies from Render/catalog jobs. Generate this lock using `uv pip compile requirements/security.in --universal --python-version 3.11 --no-annotate -o requirements/security.txt`; regenerate the development lock with its existing runtime constraints. Never use an automatic audit fix to rewrite deployment requirements. Current locks pin versions but do not require package hashes; audits detect known advisories, not all supply-chain risks.

## Continuous checks

`.github/workflows/security.yml` scans all four Python locks and the widget npm lock on relevant pushes, pull requests, manual dispatch and Mondays at 06:20 UTC. The schedule activates only when this workflow exists on the repository's default branch. The workflow has read-only repository permissions, no application secrets and time limits. Raw reports and exception decisions are uploaded for 14 days even on failure. It makes public advisory/registry requests and does not call Groq or Shopify.

Run the Python audit in an isolated environment installed from `requirements/security.txt`:

    python tools/security/audit.py --output /path/to/audit-reports

Run the Node audit without package installation or scripts:

    npm --prefix tools/widget-tests audit --package-lock-only --ignore-scripts --json

New findings, skipped/unscanned packages, malformed reports, unavailable scans and expired exceptions fail the checks. An exception matches the exact package/version and documented advisory aliases. A newly reported fix version also invalidates the exception. Findings remain in raw reports; the scan never silently excludes the whole Chroma package. These checks do not automatically block Render's independently configured deployment: review failed runs before release and configure GitHub required checks if desired.

## Chroma 1.5.9: mitigations, not an upstream fix

The project retains Chroma 1.5.9: the reviewed sources do not identify a stable corrected version for the findings below. Development releases are not treated as verified fixes.

| Advisory | Exposure and mitigation |
| --- | --- |
| [CVE-2026-45829](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) | Chroma HTTP collection creation can select unsafe model configuration. The project exposes its own chat/reset API, uses local PersistentClient, and rejects alternative persisted embeddings before search. |
| [CVE-2026-45830](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr) | Cross-tenant Chroma HTTP authorization issue. The project does not expose Chroma tenant/collection endpoints. |
| [CVE-2026-45831](https://github.com/advisories/GHSA-xph7-9rjv-w5fr) | SimpleRBAC scope checks. The project does not use this authorization provider or a Chroma HTTP server. |
| [CVE-2026-45833](https://github.com/advisories/GHSA-36p7-vc44-83pf) | Chroma collection updates can select unsafe embedding configuration. No such public update endpoint exists in this project; raw configuration/schema checks reject alternatives before searching. |

`src/chroma_security.py` checks raw collection configuration and nested raw schema before Chroma deserializers can instantiate embedding functions. Only known default/ONNX MiniLM settings are accepted, with empty or CPU-only provider configuration. The unused `type: unknown` sparse placeholder remains compatible. Remote/custom embedding names, extra model parameters and alternative nested functions fail startup, leaving readiness degraded. This guard depends on Chroma 1.5.9's raw model layout and must be reviewed whenever Chroma is upgraded.

The database directory, active manifest and local model cache must remain private, writable only by trusted operators/build jobs. Do not accept uploaded Chroma databases or client-supplied embedding settings. Integrity fingerprints are consistency checks, not signatures against someone who can rewrite local files. Do not expose a Chroma server or switch clients without reassessing these mitigations.

`tools/security/exceptions.json` records these four scoped, justified exceptions until **12 November 2026**. Expiration fails the workflow and requires a fresh review, not an automatic extension. Chroma remains affected at package level; these controls reduce this application's exposure and do not certify the library as fixed.

## Updating safely

Inspect advisories and release notes; change direct inputs, regenerate matching locks, run audits, dependency compatibility and the offline Python suite using Python 3.11. If search dependencies change, build/load/query a temporary index before deploying. Keep the previous generation recoverable. Verify the resulting GitHub run and Render readiness after pushing; local checks do not establish those remote outcomes.
