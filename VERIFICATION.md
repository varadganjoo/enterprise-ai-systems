# Maintenance verification

Scope: November 1, 2026 refresh on `refresh/maintained-suite`. Local Windows, Python 3.11.0, project `.venv`. This is evidence for a local demonstration, not production certification.

## Acceptance and checks

| Check | Result | Evidence |
|---|---|---|
| Existing functionality and new synthesis/plan regressions | PASS | `.venv/Scripts/python run.py --test`: 93 tests across nine isolated suites |
| Dependency consistency | PASS | `python -m pip check`: no broken requirements |
| Known package vulnerabilities | PASS at scan time | `python -m pip_audit --format=json --output=artifacts/dependency-audit.json`: 69 installed distributions, zero known findings after updating local pip/setuptools |
| Static compilation | PASS | `python -m compileall` on launcher, tools and all application code |
| Desktop/mobile dashboards | PASS | `python tools/browser_smoke.py`: suite directory and nine workspaces at 1440px and 390px; assets, JavaScript execution, keyboard focus, no horizontal page overflow |
| Failure handling | PASS | Browser requests intercepted with HTTP 503 and hostile error text; errors surfaced, controls re-enabled, no injected image element |
| Credential patterns | Limited manual review | Tracked source files checked for common AWS/GitHub/Google key and private-key patterns: no matches. Not an exhaustive or historical secret scan |
| Diff review | PASS | Checked input validation, model-output boundaries, asset directory scope, subprocess arguments, local bind address and process cleanup; `git diff --check` |
| Hosted CI | Pending remote execution | Windows/Linux Python 3.11/3.13 and Linux Chromium jobs configured; local success is not a claim that hosted jobs ran |
| Live model/evaluation runs | NOT RUN | No paid Gemini requests or account-specific availability checks performed |

Raw browser captures, server logs and audit JSON are in ignored `artifacts/`. The dependency audit includes development/audit tooling installed in this virtual environment, not just runtime packages. Advisory data is time-sensitive. Direct pins are checked in; transitive versions are resolved at install time.

The Windows sandbox blocked asyncio socket-pair creation before endpoint code executed. Tests and browser checks were rerun outside that sandbox. FastAPI's test client emits a deprecation warning for its httpx compatibility path; the tests pass.

## Review boundaries

Actors: one local operator, a Gemini provider, and untrusted model responses. Data: sample invoices, handbook passages, synthetic customer tickets and session memory. Assets: local SQLite data and the operator's API key. New assets are served only from `suite/`, never the repository root. The launcher accepts a bounded application number and numeric port and binds to loopback. The API key stays in ignored environment files.

The apps have no authenticated user/tenant authorization. Do not expose them as a production service. Approval identities, payment/email integrations, rate limiting, concurrent transaction guarantees, comprehensive prompt-injection resistance and PII erasure require separate work. Existing regex/provenance checks do not establish semantic truth or complete privacy protection. This refresh does not claim those controls were verified.

## Applied workflow

- Ponytail: retained plain FastAPI/HTML, shared existing dashboard behaviors, used stdlib graph ordering and subprocess test isolation; no frontend framework or deployment scaffold.
- Enterprise-app-dev/Superpowers: acceptance criteria, observed-failure debugging and verification before completion.
- OWASP: dependency audit, limited credential-pattern analysis and review of changed runtime boundaries. The GENiiPulse workflow's dependency/venv/testing principles were applied; that project's separate catalog and absent workspace override do not apply here.
- Anthropic webapp-testing: rendered browser journeys, screenshots, responsive checks and explicit server cleanup using project tooling.
- Minimalist commercial discovery, separate Spellbook scaffolding and independent Sentry review were not run: this is maintenance of an established local suite, with no new commercial scope, auth architecture or deployment target. No independent review or certification is implied.
