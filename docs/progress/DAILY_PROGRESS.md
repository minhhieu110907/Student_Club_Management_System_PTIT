### SCMS Day 01 — 2026-10-21 — STATUS: VERIFIED
- Branch / commit / PR: `feature/day01-foundation`; Slice 01 commit `39bc66f`; Slice 02 commit `71d73de`; no PR recorded.
- Implemented (based on code inspection):
  - Slice 01: Minimal FastAPI skeleton with Python 3.12 packaging, locked dependencies, non-root Docker runtime, `GET /api/v1/health`, and Pytest/HTTPX health endpoint coverage.
  - Slice 02: Nginx static frontend and `/api/` reverse proxy, Docker Compose stack for Nginx/FastAPI/MySQL 8.4.4, named MySQL volume, separated `edge` and internal `data` networks, API healthcheck, and authenticated MySQL `SELECT 1` healthcheck.
- Tests run and results (include commands):
  - `python -m pytest` from `backend/`: PASS — health endpoint test passed.
  - `docker compose up -d --build`: PASS — images built and all three services started.
  - Proxied `GET http://localhost:8080/api/v1/health`: PASS — returned `{"status":"ok"}`.
  - Persistence check: PASS — a MySQL test record survived container recreation; the temporary test table was removed afterward.
- Docker / environment status: Nginx, API, and MySQL were running; API and MySQL reported healthy. Nginx served the frontend at `http://localhost:8080` and proxied API requests through the Compose service name `api`.
- Important architectural decisions (ADR): Only Nginx publishes an application host port. Nginx and API share the `edge` network; API and MySQL share the internal `data` network. MySQL persists data in the named `mysql_data` volume. No separate ADR was required for this foundation slice.
- Schema / migration changes: None. DBML V1.3 was not modified, and no SQLAlchemy models, Alembic migrations, or application schema were created on Day 01.
- Open bugs and tech debt: No known Day 01 blocker. Database schema correctness against MySQL 8.4.4 remains unverified until the Day 02 ORM/Alembic work.
- Deferred work: Business modules, authentication, SQLAlchemy models, Alembic migrations, seed data, Redis, workers, transactional outbox processing, and AI integration.
- Next day prerequisites: Implement SQLAlchemy models and the initial Alembic migration, then verify generated MySQL schema constraints, indexes, foreign keys, and generated-column behavior against DBML V1.3.
- Evidence links or filenames: `backend/app/main.py`, `backend/tests/test_health.py`, `backend/Dockerfile`, `backend/requirements.lock`, `compose.yaml`, `frontend/nginx.conf`, `frontend/index.html`, `.env.example`, `README.md`, and `docs/database/scms_v1_3_outbox.dbml`.

### SCMS Day 02 — 2026-10-26 — STATUS: VERIFIED
- Branch / commits: `feature/day02-database`; ORM `0bf1cbe`; Alembic `b87f6eb`; live MySQL verification `e0583c7`; deterministic seed `1352505`; merged to `main` by PR #3 (`25a7c3f`).
- Slice 01: Database Audit completed against DBML V1.3.
- Slice 02: SQLAlchemy 2.x Typed Declarative ORM mappings completed for all 18 tables using the shared metadata registry and modular domain-first organization.
- Metadata parity verification: PASS — 29 foreign key constraints including 4 composite foreign keys, 17 named CHECK constraints, 20 non-primary-key unique keys, 5 STORED generated columns, and 6 approved FK-supporting indexes.
- Python 3.12 Docker verification: PASS on Python 3.12.15 — metadata tests 7/7, health test 1/1, and full test suite 8/8.
- Dependency status: Runtime and test dependencies were resolved and locked in a clean Python 3.12 environment; the Pytest 8.x project contract is preserved.
- Known issue / deferred review: `ai_usage_records.estimated_cost` currently uses Python `float` typing for a MySQL `DECIMAL(18,8)` column; Python typing is deferred for later review.
- Alembic / physical verification: Initial revision `20261026_01` was added and verified against disposable MySQL 8.4.4 resources; development MySQL and persistent volumes were not used.
- Deterministic demo seed: Added for all 18 tables with idempotency, rollback, collision, environment-guard, relationship, and business-invariant integration coverage.
- Deferred work: `ai_usage_records.estimated_cost` Python `float` typing remains deferred for later review. No production/shared database migration was performed.

### SCMS Day 03 — 2026-10-27 — STATUS: VERIFIED
- Branch / commits / PR: `feature/day03-quality-gate`; pytest/Ruff `ce73bba`; structured logging/request correlation `5ecd7a8`; centralized exception handling `05592ee`; liveness/readiness `9a87379`; CI workflow `df354e0`; merged through PR #4 as main commit `74d8227`.
- Implemented (based on code inspection): Strict pytest markers and integration fail-closed contract; transitional Ruff scope; JSON application/access logging; validated request IDs with async context isolation; standard secure API error responses; dependency-free liveness; pooled MySQL/Alembic readiness with bounded timeouts and shutdown disposal.
- Merged CI scope: Three-job GitHub Actions workflow for quality, isolated MySQL 8.4.4 integration, and production Docker build. Readiness integration adds migrated, empty, wrong-revision, and missing-URL cases.
- Tests run for Slice 05 candidate: Python 3.12 ordinary suite PASS (`51 passed, 13 deselected`); integration collection PASS (`13/64 collected`, comprising 9 existing and 4 readiness tests); missing-URL CI mode failed closed with expected pytest exit 4; disposable MySQL 8.4.4 integration PASS (`13 passed, 51 deselected`); `pip check` PASS; workflow YAML structural parse PASS; local production Docker build PASS.
- Docker / environment status: Ordinary verification used `--network none`. Live integration used one uniquely named/labeled MySQL 8.4.4 container with tmpfs data and a random loopback-only host port; ownership cleanup passed with no run resources remaining. The production image built locally without push. PR #4 and merge commit `74d8227` confirm owner review and merge of the CI workflow; Git history does not retain individual hosted job logs, so no additional hosted-run counts are asserted here.
- Safety decisions: CI uses synthetic credentials, a fresh MySQL service without persistent volumes, explicit migrations, seven isolated schemas, and a helper that refuses non-CI or non-loopback targets. Existing Windows verification harnesses and Compose topology are unchanged.
- Open issue: Existing `StarletteDeprecationWarning` for the current `httpx`/`TestClient` combination remains non-blocking.

### SCMS Day 04 — 2026-10-29 — STATUS: VERIFIED (MERGED)
- Branch / commits / PR: `feature/day04-security-primitives`; security primitives `96f2254`; registration/session foundation `ca7495e`; login/current-user authentication `7080f2b`; refresh rotation/logout `5c29413`; docs `bc305e9`; merged to `main` via PR #5 (`6400a56`).
- Implemented: Argon2id password hashing; public STUDENT registration; uniform login failures; HS256 access JWTs; `GET /api/v1/auth/me`; opaque refresh credentials stored only as SHA-256 digests; atomic initial-session issuance; strict refresh rotation; rotated-token reuse family revocation; idempotent logout; HttpOnly refresh cookie; exact Origin allowlist validation.
- Lifetimes and policies: access JWT 10 minutes; refresh token sliding lifetime 7 days capped by the family absolute lifetime of 30 days; family retention timestamp 30 days after absolute expiry; cookie uses `HttpOnly`, `SameSite=Lax`, auth-scoped Path, and environment-aware `Secure` with production fail-closed validation.
- Local verification (2026-10-28): actual-route disposable-MySQL E2E gate PASS (`1 passed`); ordinary tests PASS (`203 passed, 26 deselected`); disposable MySQL 8.4.4 integration PASS (`26 passed, 203 deselected`); Ruff lint and format PASS; `pip check` PASS; production Docker image build PASS; `git diff --check` PASS.
- Concurrency and failure evidence: family-first `SELECT ... FOR UPDATE` serializes refresh; predecessor is flushed rotated before successor insert to preserve the generated single-current-token guard; concurrent use of one predecessor deliberately causes one rotation and one strict-reuse family revocation; injected successor failure rolls back predecessor rotation.
- Schema / migration changes: None. Authentication uses the existing `users`, `refresh_token_families`, and `refresh_tokens` schema.
- Known V1 limitations: concurrent retry or multi-tab refresh can trigger strict family revocation; logout does not blacklist already issued access JWTs, whose residual validity is at most 10 minutes; no logout-all-sessions, cleanup job, or Redis rate limiting.
- Evidence: `docs/decisions/0001-authentication-security-foundation.md`, `backend/app/core/security/`, `backend/app/modules/identity/`, `backend/tests/test_auth_api.py`, `backend/tests/test_refresh_service.py`, and `backend/tests/integration/test_registration.py`.

### SCMS Day 05 — 2026-11-01 — STATUS: VERIFIED (MERGED)
- Branch / commits / PR: `feature/day05-club-creation` (`9bc6aab`); merged to `main` via PR #6 (`b66a041`).
- Implemented (dựa trên code & git history):
  - Backend Club Creation & System Admin Review (`backend/app/modules/clubs/`): `POST /api/v1/club-requests`, `GET /api/v1/club-requests/mine`, `GET /api/v1/club-requests/{request_id}`, `GET /api/v1/admin/club-requests/pending`, `POST /api/v1/admin/club-requests/{request_id}/approve`, `POST /api/v1/admin/club-requests/{request_id}/reject`.
  - Atomic approval tạo `Club` + founder `MANAGER` `ClubMembership` trong một transaction; khóa dòng request bằng `SELECT ... FOR UPDATE` chống duyệt trùng.
  - Frontend Vanilla JS (`frontend/index.html`, `frontend/css/styles.css`, `frontend/js/app.js`, `frontend/js/app.test.js`): auth flow (kèm refresh-token serialization), tạo yêu cầu lập CLB (Student), và màn hình duyệt yêu cầu (Admin); bổ sung Prettier config (`.prettierrc.json`, `.prettierignore`) và UI/UX PDF references (`UI_UX/`).
- Verification status: Các kịch bản Club Creation & Admin Review đã được kiểm chứng gộp trong bộ test tích hợp và unit test tại mốc Day 06 (`test_club_requests.py`, `test_club_api.py`, `frontend/js/app.test.js`). Hosted GitHub Actions logs cho PR #6 không lưu trong local Git.
- Evidence: `backend/app/modules/clubs/`, `backend/tests/test_club_api.py`, `backend/tests/integration/test_club_requests.py`, `frontend/index.html`, `frontend/js/app.js`, `frontend/js/app.test.js`.

### SCMS Day 06 — 2026-11-19 — STATUS: VERIFIED (MERGED)
- Branch / commits / PR: `feature/day06-membership` (`43015a9`); merged to `main` via PR #7 (`ac3cc4d`).
- Implemented:
  - Membership Lifecycle API (`backend/app/modules/clubs/`): `GET /api/v1/clubs`, `GET /api/v1/clubs/mine`, `POST /api/v1/clubs/{club_id}/membership-applications`, `GET /api/v1/membership-applications/mine`, `GET /api/v1/memberships/mine`, `GET /api/v1/clubs/{club_id}/membership-applications/pending`, `POST /api/v1/membership-applications/{application_id}/approve`, `POST /api/v1/membership-applications/{application_id}/reject`, `POST /api/v1/memberships/{membership_id}/leave`, và `GET /api/v1/clubs/{club_id}/members`.
  - Club-scoped authorization (`backend/app/modules/clubs/authorization.py` với `require_active_manager`).
  - Bounded pagination (`page >= 1`, `1 <= page_size <= 100`) và single-JOIN query (`ClubMembership` + `User.full_name`) cho `GET /api/v1/clubs/{club_id}/members` (không N+1, không lộ email/password hash/token).
  - Frontend Vanilla JS cập nhật giao diện ứng tuyển, duyệt đơn, rời CLB và test tương ứng.
- Concurrency & Security mechanisms:
  - Sửa lỗi stale SQLAlchemy identity-map khi khóa dòng bằng `.execution_options(populate_existing=True)` trên `SELECT ... FOR UPDATE`, ngăn tình trạng `approve` và `reject` đồng thời cùng commit.
  - Bảo vệ invariant "final active MANAGER cannot leave an active club" bằng khóa dòng `Club` (`FOR UPDATE`) trước khi kiểm tra số lượng active `MANAGER`, bảo toàn ít nhất 1 active `MANAGER` khi có concurrent leave requests mà không deadlock.
  - Giữ `lock_users` + DB unique constraints (`uq_membership_pending`, `uq_membership_active`, `uq_club_memberships_source_application_id`).
- Local verification results (2026-11-19):
  - Ordinary tests (`.\.venv\Scripts\python.exe -m pytest -m "not integration" -q`): **PASS — `218 passed, 46 deselected`**.
  - Full fail-closed MySQL 8.4.4 integration suite (`.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -m integration --require-integration-env -q` trên 9 isolated schemas disposable): **PASS — `46 passed, 0 skipped`**.
  - Frontend JS tests (`node --test frontend\js\app.test.js`): **PASS — `17 passed, 0 failed`**.
  - Ruff lint & format check (Day 06 & CI contract scope): **PASS — `12 files already formatted`**.
  - `git diff --check`: **PASS**.
  - Lưu ý: Đây là kết quả xác minh **local**; log chạy thực tế trên hosted GitHub Actions cho PR #7 không có trong local Git nên không suy diễn trạng thái hosted CI từ kết quả local.
- Schema / migration changes: None (dùng schema `20261026_01`).
- Next step: Phase Events & Registration (`feature/day07-events`).
- Evidence: `backend/app/modules/clubs/authorization.py`, `backend/app/modules/clubs/repository.py`, `backend/app/modules/clubs/service.py`, `backend/app/modules/clubs/router.py`, `backend/tests/test_membership_api.py`, `backend/tests/integration/test_membership_lifecycle.py`, `frontend/js/app.js`, `frontend/js/app.test.js`.

### SCMS Day 07 & Day 08 — MERGED TO `main` (2026-11-26)
- Ghi chú kiểm chứng lịch sử: Tại thời điểm đồng bộ `main` (`cf4af52`), module Events & Registration (`backend/app/modules/events/`) và Event Tasks (PR #10, merge commit `cf4af52934960670c20f8e9b09c97356a11717a0`) đã được hợp nhất vào `main`. Không tự suy diễn lại số liệu chạy test riêng lẻ của Day 07 vì log chạy trước đó không nằm trong phạm vi xác minh hiện tại; toàn bộ test của Events và Tasks đều nằm trong bộ regression chạy tại mốc Day 09 bên dưới.

### SCMS Day 09 — 2026-11-27 — STATUS: IN PROGRESS (COMMITTED, PENDING REVIEW FIXES)
- Branch / commit: `feature/day09-gemini-ai` (`2168953`, tách từ `main` tại `cf4af52`).
- Implemented:
  - Provider abstraction (`AI_PROVIDER=mock|gemini`) với `MockAIProvider` (demo/offline không cần API key) và `GeminiAIProvider` dùng SDK `google-genai==1.75.0` (fail-closed khi thiếu `GEMINI_API_KEY`).
  - Allowlist đúng 4 read-only tools (`list_upcoming_events`, `get_my_registrations`, `get_my_tasks`, `get_event_progress`) gọi qua `events/service.py` và `tasks/service.py` bằng danh tính JWT `CurrentUserResponse`.
  - Shared request-scoped `ToolBudget` (`15s` / `3` calls / `32 KiB` UTF-8) và `ToolContext` capability binding.
  - Endpoints `POST /api/v1/ai/chat`, `GET /api/v1/ai/conversations`, `GET /api/v1/ai/conversations/{conversation_id}` cùng transaction 3-phase (không giữ DB transaction/connection khi chờ provider).
  - Minimal frontend AI assistant panel (`frontend/index.html`, `frontend/js/app.js`) escape HTML an toàn qua `escapeHtml()`.
- Local verification results (2026-11-27, trước khi commit `2168953`):
  - Ruff lint & format check (16 files AI/CI scope): **PASS** (`All checks passed!`, `16 files already formatted`).
  - Ordinary tests (`.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -m "not integration" -q`): **PASS — `250 passed, 68 deselected`**.
  - Disposable MySQL 8.4.4 integration suite (`.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -m integration --require-integration-env -q` trên 12 isolated schemas): **PASS — `68 passed, 250 deselected`**.
  - Frontend JS (`node --check frontend/js/app.js` & `node --test frontend/js/app.test.js`): **PASS — `28 passed, 0 failed`**.
  - Backend Docker build (`docker build --file Dockerfile --tag scms-backend:day09-verify .`): **PASS** (đã xóa image tạm).
  - `git diff --check`: **PASS**.
  - Lưu ý: Gemini live API chưa được test bằng `GEMINI_API_KEY` thật; các test Gemini sử dụng mocked `genai.Client` và `MockAIProvider`.
- Schema / migration changes: None (dùng 5 bảng AI có sẵn trong `20261026_01`).
- Open bugs and tech debt: Xem chi tiết 7 review findings (trong đó có P1 `AI-01` về crash/stale lease trên `ai_turns.inflight_guard`) tại `docs/progress/DAY09_AI_HANDOFF.md`.
- Hardening pass (2026-11-28, working tree chưa commit trên `feature/day09-gemini-ai`):
  - **AI-01 (Fixed):** Khởi tạo `lease_expires_at` (`request_deadline_seconds + 15s` UTC) và `lease_generation=1`, thêm atomic stale-lease recovery dưới `ai_conversations` `FOR UPDATE` + `ai_turns` current read (`FOR UPDATE`), fencing `claim_turn_completion()` theo `(id, status='RUNNING', lease_generation)`, và catch-all `except Exception:` đóng turn an toàn.
  - **AI-02 (Fixed in code, pending MySQL run):** Thêm migration tăng dần `20261128_01_ai_conversation_create_key.py` (`ai_conversations.create_request_key BINARY(16) NULL` + `uq_ai_conversation_create_request (owner_user_id, create_request_key)`) cho phép idempotency cả khi `conversation_id=None`; sửa retry semantics trả lại trạng thái lỗi đã lưu khi turn `FAILED` (không chạy lại provider); frontend giữ nguyên `client_request_key` khi network retry và tạo key mới khi explicit retry sau HTTP error.
  - **AI-03 (Verified & Fixed):** Kiểm chứng `google-genai==1.75.0` (`HttpOptions.timeout` tính bằng ms, `GenerateContentConfig.http_options` truyền từng round, tắt SDK retry ngầm bằng `HttpRetryOptions(attempts=1)`).
  - **AI-04 (Assessed — No issue found):** Sau Phase 1 `commit()`, `session.in_transaction()` là `False`; bổ sung test xác minh trên MySQL.
  - **AI-06 (Fixed & Verified):** `resetAiUiState()` + `AbortController` được gọi trong `replaceSession()` và `invalidateSession()`, chặn delayed response của tài khoản cũ.
  - Kiểm thử sau hardening (2026-11-28): Ruff check & format PASS; ordinary tests PASS (`253 passed, 74 deselected`); frontend JS PASS (`30 passed, 0 failed`); MySQL 8.4.4 integration (`74` tests) & Docker build **NOT RUN** trong lượt này do Docker Desktop daemon chưa bật.
- Next step: Xử lý các review findings được Owner duyệt (ưu tiên `AI-01`, `AI-02`), chạy lại regression và mở PR vào `main`.
- Evidence: `backend/app/modules/ai/`, `backend/tests/test_ai_tool_executor.py`, `backend/tests/test_ai_provider_and_api.py`, `backend/tests/integration/test_ai_assistant.py`, `docs/progress/DAY09_AI_HANDOFF.md`.
