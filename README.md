# Enterprise AI Systems

[![CI](https://github.com/varadganjoo/enterprise-ai-systems/actions/workflows/ci.yml/badge.svg)](https://github.com/varadganjoo/enterprise-ai-systems/actions/workflows/ci.yml)

Nine focused Python applications exploring reliable AI workflows: source-backed answers, structured extraction, approval gates, read-only analytics, model routing, persistent memory, and event-driven case handling.

**The model proposes. Application code checks.** Each workspace exposes evidence, decisions, or state transitions so results can be inspected.

## Quickstart

Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip setuptools
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set GEMINI_API_KEY.
.venv\Scripts\python run.py
```

On macOS/Linux use `.venv/bin/python` and `cp .env.example .env`.

Open **http://127.0.0.1:8000** for the suite directory. In another terminal, start a workspace:

```powershell
.venv\Scripts\python run.py 1
```

Numbers 1–9 select ports 8001–8009. The directory does not automatically start applications. Each app has interactive API documentation at `/docs`. Keep the complete checkout: dashboards share assets in `suite/`.

## Workspaces

| # | Application | What the code checks |
|---|---|---|
| 01 | [Cited Knowledge Agent](01-cited-knowledge-agent) | BM25 + embedding retrieval, rank fusion, quotation offsets, source currency |
| 02 | [Document Extraction](02-document-extraction) | Text invoice extraction, arithmetic, purchase orders, confidence review thresholds |
| 03 | [Support Operator](03-operator-agent) | Allowed tools, bounded iterations, outbound rules, separate approval |
| 04 | [Analytics Copilot](04-analytics-copilot) | Named metrics, parsed SQL, allowed tables, row limits, read-only SQLite |
| 05 | [Model Router](05-model-router) | Heuristic classification, cheap-answer verification, escalation and fallback |
| 06 | [Memory Service](06-memory-service) | Session slots, corrections, supersession and pattern-based PII masking |
| 07 | [Claim Auditor](07-claim-auditor) | Quotation existence and source status, with explicit verdict rules |
| 08 | [Case Workflow](08-case-workflow) | State transitions, category caps, event replay and duplicate-event handling |
| 09 | [Multi-Hop Brief](09-multi-hop-brief) | Intermediate citations and dependency gating before synthesis |

## Model settings

A root `.env` configures all nine applications. An application's own `.env` takes precedence; exported environment variables override both.

| Variable | Default |
|---|---|
| `GEMINI_API_KEY` | Required for model calls |
| `GEMINI_MODEL` | `gemini-3.8-flash` |
| `GEMINI_CHEAP_MODEL` | `gemini-3.5-flash-lite` |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` |

Defaults were checked against Google's [model catalog](https://ai.google.dev/gemini-api/docs/models) during this refresh. Availability and quota depend on your account. Requests have a 60-second timeout. Dashboards open without a key; model operations require one. The knowledge agent reports index readiness at `/health`.

## Tests and evaluations

```powershell
# All suites, isolated to prevent their app packages from colliding.
.venv\Scripts\python run.py --test

# One suite.
cd 09-multi-hop-brief
..\.venv\Scripts\python -m pytest tests -q
```

Tests use controlled inputs without paid model calls. CI runs on Windows and Linux, Python 3.11 and 3.13. Existing live evaluation scripts in applications **01–06** consume API quota:

```powershell
cd 01-cited-knowledge-agent
..\.venv\Scripts\python evals/run_eval.py
```

Evaluate quality, refusals, latency and usage on representative tasks before claiming performance. Router rates are illustrative assumptions. Fair savings comparisons need a separately measured baseline; token savings are not invented when no baseline was run.

For browser checks, install `requirements-dev.txt`, run `python -m playwright install chromium`, then `python tools/browser_smoke.py` using the virtual environment. This starts and cleans up isolated local servers on ports 18000–18009, checks desktop/mobile layouts, and saves screenshots in ignored `artifacts/`.

## Scope

These are local engineering demonstrations with sample data, not an authenticated multi-tenant service. The launcher binds to loopback. Sending and refund execution update local records; they do not deliver email or move money. Approval is a workflow step rather than verified separation of authenticated people.

Quotation matching proves where text occurs, not that every conclusion follows from it. Claim-auditor contradiction rules are narrow. Multi-hop retrieval uses keyword overlap, separate from application 01's hybrid search. PII detection is pattern-based. Forgetting memory marks rows inactive rather than permanently erasing them. Financial examples use floats and need decimal handling for real accounting.

## Maintenance

Root installation uses the same pins as application manifests. Dependabot proposes weekly package and GitHub Actions updates. [CHANGELOG.md](CHANGELOG.md) records actual maintenance. [VERIFICATION.md](VERIFICATION.md) records verification evidence and remaining limits.

## Development

I implemented the applications and used AI assistance for documentation and evaluations.
