# Specialized Repository Agents

This repository is maintained through ten specialized agents that are scoped to the completed phases and the current implementation boundary.

## Agent 1 — Repository Audit
- Audits the repository structure, dependency boundaries, and existing phase implementations.
- Preserves backward compatibility and identifies duplicate or partial implementations.

## Agent 2 — Phase 3 Implementation
- Extends the causal multi-timeframe and signal quality pipeline for Phase 3.
- Maintains deterministic, look-ahead-safe evaluations and existing public APIs.

## Agent 3 — Phase 3 Testing
- Validates Phase 3 behavior with unit, regression, boundary, and failure-focused tests.
- Ensures no new logic introduces future-data leakage or incompatible outputs.

## Agent 4 — Phase 4 Implementation
- Completes the market-structure intelligence layer around confirmed swing events.
- Preserves the historical compatibility wrappers and event semantics.

## Agent 5 — Phase 4 Testing
- Verifies structure state, break confirmation, event de-duplication, and compatibility behavior.
- Confirms that unconfirmed swings do not influence downstream decisions.

## Agent 6 — Integration
- Coordinates the interaction between signal, structure, and contextual components.
- Prevents Phase 5 work from being introduced before the Phase 3/4 contract is stable.

## Agent 7 — Regression Testing
- Executes regression checks that protect historical behavior, public contracts, and legacy imports.
- Validates deterministic replay and backward compatibility.

## Agent 8 — Performance Validation
- Measures the cost and determinism of causal selection paths and cached prefixes.
- Ensures Phase 3/4 changes remain production-safe under repeated evaluation.

## Agent 9 — Documentation
- Maintains implementation notes, validation reports, and agent guidance.
- Keeps user-facing documentation aligned with repository behavior.

## Agent 10 — Final Validation, Git, Commit, and Push
- Runs compile checks, test suites, preflight validation, and diff hygiene checks.
- Pushes only after the repository is verified and synchronized.
