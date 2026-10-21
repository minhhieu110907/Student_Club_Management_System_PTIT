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