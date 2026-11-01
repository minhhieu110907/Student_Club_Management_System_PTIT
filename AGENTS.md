# SCMS — Codex Engineering Instructions

## 1. Project Context

SCMS (Student Club Management System) is a 21-day fullstack educational project designed to demonstrate production-minded backend engineering.

Technology stack:
- Backend: FastAPI, SQLAlchemy, Alembic, Pydantic
- Frontend: HTML, CSS, Vanilla JavaScript
- Database: MySQL 8
- Infrastructure: Docker Compose, Nginx, Redis
- Background processing: Worker Queue, Transactional Outbox
- AI: LLM integration with authorized read-only tools
- Testing: Pytest, integration tests, concurrency tests
- CI: GitHub Actions

Architecture: Lightweight Modular Monolith.

## 2. Source of Truth

Before making significant changes, consult:

1. `docs/SCMS_MASTER_CONTEXT.md` — project scope, roadmap, architecture decisions.
2. `docs/progress/DAILY_PROGRESS.md` — current implementation status.
3. `docs/database/scms_v1_3_outbox.dbml` — database design baseline.
4. `docs/decisions/` — approved architecture decisions.
5. Existing code, migrations and tests — actual implementation.

Do not assume planned features are already implemented.

When documentation conflicts with code, report the discrepancy before making architectural changes.

## 3. Engineering Principles

- Preserve the Lightweight Modular Monolith architecture.
- Organize business logic by domain.
- Keep routers thin.
- Services own business rules and transaction boundaries.
- Repositories handle persistence, not business decisions.
- MySQL is the source of truth.
- Redis must not determine critical business correctness.
- Enforce authorization on the backend and at resource level.
- Avoid unnecessary abstractions, frameworks and premature optimization.
- Do not introduce microservices, React, Kafka or Kubernetes without approval.

## 4. Database & Concurrency

- Use Alembic for schema migrations.
- Do not change database constraints without explaining the impact.
- Define transaction boundaries explicitly.
- Use database constraints and atomic operations for concurrency-sensitive workflows.
- Handle rollback, duplicate requests and relevant retry scenarios.
- Do not use Redis distributed locks to replace database consistency mechanisms.
- Keep demo seeds separate from tests and production migrations.

## 5. Security

- Never hardcode secrets or commit real credentials.
- Do not log passwords, access tokens, refresh tokens or API keys.
- Validate all external inputs.
- Enforce club-scoped authorization.
- Prevent IDOR/BOLA vulnerabilities.
- Protect refresh-token rotation and revocation.
- AI tools must use an explicit allowlist and validated inputs.
- AI tool execution must use authenticated identity and existing business services.

## 6. Testing & Quality

For each vertical slice:

1. Identify business invariants and failure cases.
2. Implement the smallest correct solution.
3. Add appropriate unit, integration, API and security tests.
4. Add concurrency tests for race-prone operations.
5. Run relevant tests and report the actual results.
6. Review regressions before completing the task.

Never claim a test passed unless it was executed successfully.

Never silently remove or weaken tests to make CI pass.

## 7. Logging & Reliability

- Use structured logging and request/correlation IDs.
- Do not expose sensitive data in logs.
- Make background jobs retry-safe where applicable.
- Transactional Outbox delivery must tolerate duplicate publishing.
- Treat outbox publishing as at-least-once, not exactly-once.
- Ensure cache failures do not corrupt authoritative business data.

## 8. Working Agreement

For every implementation task:

1. Read the relevant code and project context.
2. State a concise implementation plan.
3. Identify affected files and modules.
4. Implement only the requested scope.
5. Run appropriate checks.
6. Summarize changes and test evidence.
7. Report unresolved issues, risks and follow-up work.

Do not refactor unrelated modules.

Do not modify the approved architecture or expand project scope without explicit approval.

## 9. Definition of Done

A feature is DONE only when:

- Its acceptance criteria are satisfied.
- Relevant automated tests pass.
- Authorization and failure cases are covered.
- Logging and error handling are appropriate.
- Existing functionality is not knowingly broken.
- The implementation is consistent with the current project architecture.

If verification is incomplete, report PARTIAL or NOT VERIFIED.

## 10. Progress Documentation

At the end of an approved task, propose updates to:

`docs/progress/DAILY_PROGRESS.md`

Document:
- Completed work
- Tests executed and results
- Architecture decisions
- Known issues and technical debt
- Next steps

Do not mark an entire day DONE without user approval.

## 11. UI/UX Design Source of Truth

- Before implementing or changing UI, inspect `UI_UX/SCMS_Desktop.pdf`, `UI_UX/SCMS_Foundation.pdf`, and `UI_UX/SCMS_Mobile_and_State.pdf`, and record the relevant pages/frames. Use Desktop for matching desktop screens, Mobile and State for responsive layouts and interaction states, and Foundation for documented tokens, typography, and shared styling. Do not invent specifications absent from these references or claim Figma/PDF fidelity without checking the corresponding pages.
- Use HTML, CSS, and vanilla JavaScript. Reuse existing components, classes, assets, and conventions. Do not introduce React, another frontend framework, or a replacement design system without owner approval.
- Deliver every user-facing module as one Backend + Frontend + real-API vertical slice; do not defer frontend implementation or integration. Use actual API responses and existing authentication, and include appropriate loading, success, error, and empty states. UI completion also requires correct authorization and data behavior.
- Respect both desktop and mobile references. Use semantic HTML, accessible labels, keyboard-operable controls, safe DOM rendering for untrusted content, and layouts without unnecessary horizontal overflow.
- Where a matching design exists, Figma/PDF controls visual presentation; the actual ORM/schema and backend API contracts control technical behavior. Do not automatically implement out-of-scope backend features shown by a design. Document PDF/business conflicts instead of inventing behavior.
- Verify relevant screens at desktop and mobile widths, exercise UI actions against real endpoints where possible, record the PDF pages used, and report known visual deviations. Do not claim browser E2E PASS when browser interaction was not completed.

## 12. Code Style, Readability & Formatting

- Readability and maintainability take priority over minimizing line count. Use 2-space indentation for JavaScript, HTML, and CSS, and 4-space indentation for Python in accordance with Ruff.
- Never compress an entire function into one line or place multiple independent statements on the same line. Use explicit multi-line blocks for conditionals, loops, functions, async functions, and `try`/`catch`/`finally`, and separate meaningful logical steps with blank lines.
- Prefer descriptive names, clear guard clauses and early returns, limited nesting, and reasonably sized functions. Keep authentication, refresh-token coordination, authorization, API error handling, and other asynchronous flows especially easy to inspect.
- Prefer readable multi-line HTML and template markup over dense one-line strings while preserving safe escaping of untrusted values. Comments should explain decisions, invariants, and non-obvious behavior rather than restating the code.
- Never trade security, performance, or correctness for shorter syntax. Do not introduce unnecessary abstractions or large-scale refactors solely for formatting.
- Use existing formatter configuration when present. Use Prettier for HTML, CSS, and JavaScript when available, with a preferred print width of 100 and 2-space indentation; use Ruff for Python. If Prettier configuration is absent, propose a minimal `.prettierrc.json` and `.prettierignore` without adding unnecessary frontend runtime dependencies.
- Treat formatting as a standard verification gate before owner review. Check consistent formatting, remove dense one-line functions and excessive nesting, run relevant syntax, lint, formatting, and behavioral tests, keep the change scoped, and distinguish formatting-only changes from behavioral changes in the handoff.
