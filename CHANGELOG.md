# Changelog

## 2026-11-01 — Maintenance refresh

- Updated published Python package pins across all nine applications; added the missing SQLGlot requirement and a root installer. Removed a redundant direct NumPy pin (BM25 still installs it transitively).
- Added root environment configuration, overridable Gemini models, and 60-second API timeouts. Kept documented current model defaults rather than renaming them speculatively.
- Fixed multi-hop synthesis being skipped on valid evidence. Validate graph size, required hops, unique identifiers, known dependencies and cycles; execute prerequisites first and pass their answers to dependent hops.
- Migrated analytics startup to FastAPI lifespan. Removed fabricated router token-savings values and incorrect rate aliases for arbitrary configured models.
- Added a suite directory, shared dashboard styling/navigation, responsive forms, keyboard focus and reduced-motion support. Surface service failures before rendering successful results; render memory error text without HTML interpretation.
- Added a local launcher, isolated suite runner, endpoint regressions, and desktop/mobile browser smoke checks including simulated backend failures.
- Added Windows/Linux CI, browser checks and weekly dependency-update proposals. Corrected setup instructions, evaluation coverage and application limitations.

Historical policy documents remain as intentional current/superseded fixtures for retrieval and audit examples.
