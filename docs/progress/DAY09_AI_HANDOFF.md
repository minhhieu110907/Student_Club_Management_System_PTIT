# SCMS Day 09 — Gemini AI Read-only Tool Calling Handoff

## 1. Branch & Commit Hash
- **Repository:** `minhhieu110907/Student_Club_Management_System_PTIT`
- **Branch:** `feature/day09-gemini-ai`
- **Base commit (`main`):** `cf4af52934960670c20f8e9b09c97356a11717a0` (PR #10 — Day 08 Event Tasks)
- **Implementation commit:** `2168953` (`feat(ai): add Gemini read-only tool calling`)

## 2. Kiến trúc implementation thực tế
- **Config (`backend/app/modules/ai/config.py`):** `build_ai_settings()` đọc `AI_PROVIDER` (`mock` | `gemini`, mặc định `mock`), `GEMINI_API_KEY`, `GEMINI_MODEL` (mặc định `gemini-2.5-flash`), `AI_PROVIDER_TIMEOUT_SECONDS` (`15.0`), `AI_MAX_TOOL_CALLS` (`3`), `AI_MAX_TOOL_OUTPUT_BYTES` (`32768`), `AI_REQUEST_DEADLINE_SECONDS` (`15.0`). Nếu `AI_PROVIDER=gemini` mà thiếu key -> ném `AIConfigurationError` (fail-closed, không fallback `mock`).
- **Provider (`backend/app/modules/ai/provider.py`):**
  - `MockAIProvider`: demo offline không cần API key, định tuyến prompt sang tool tương ứng thông qua `AIToolExecutor`.
  - `GeminiAIProvider`: dùng `google-genai==1.75.0` (`genai.Client` + `types.HttpOptions(timeout=...)`), tắt Automatic Function Calling (`disable=True`), tự điều phối vòng lặp tối đa `max_tool_calls + 1` lượt và sanitize lỗi SDK/timeout.
- **Tool Executor (`backend/app/modules/ai/tool_executor.py`):** `bind_authenticated_request()` tạo `ToolContext` (identity-only `eq=False`) gắn chặt `CurrentUserResponse` từ JWT.
- **Persistence (`repository.py`, `service.py`, `router.py`):** Tái sử dụng 5 bảng AI đã có trong migration `20261026_01` (`ai_conversations`, `ai_turns`, `ai_messages`, `ai_usage_records`, `ai_tool_executions`).
- **Frontend (`frontend/index.html`, `frontend/js/app.js`):** Panel `#ai-assistant-panel` gọi `POST /api/v1/ai/chat`, escape toàn bộ output bằng `escapeHtml()`.

## 3. API & 4 Read-only Tools
- **Endpoints:**
  - `POST /api/v1/ai/chat` — gửi prompt (tạo hội thoại mới hoặc tiếp tục `conversation_id` thuộc sở hữu user).
  - `GET /api/v1/ai/conversations` — liệt kê hội thoại của user (bounded pagination `page_size <= 50`).
  - `GET /api/v1/ai/conversations/{conversation_id}` — xem chi tiết hội thoại & messages thuộc sở hữu user.
- **Allowlist 4 Read-only Tools:**
  1. `list_upcoming_events` → `app.modules.events.service.list_events(..., upcoming_only=True)`
  2. `get_my_registrations` → `app.modules.events.service.get_my_registrations(...)`
  3. `get_my_tasks` → `app.modules.tasks.service.get_my_tasks(...)`
  4. `get_event_progress` → `app.modules.tasks.service.get_event_task_progress(...)`
- Mọi argument DTO dùng Pydantic `ConfigDict(extra="forbid", strict=True)` để chặn forged `user_id` hoặc extra fields.

## 4. Shared Budget
- Thực thi tại `backend/app/modules/ai/budget.py` (`ToolBudget`, bảo vệ bằng `RLock`):
  - **Time deadline:** `15.0` giây tính từ lúc khởi tạo request budget.
  - **Call limit:** tối đa `3` tool calls / request (tool không hợp lệ/sai schema cũng tiêu thụ slot).
  - **Output size limit:** tối đa `32 KiB` (`32768` bytes) tổng payload UTF-8 tích lũy qua các tool calls trong cùng request.

## 5. Transaction Lifecycle
- **Phase 1 (`service.py:81-161`):** Tạo hoặc khóa dòng `ai_conversations` (`FOR UPDATE`), ghi `ai_turns (RUNNING)`, `ai_messages (USER)`, `ai_usage_records (PENDING)` rồi gọi `session.commit()` trước khi gọi provider.
- **Phase 2 (`service.py:163-190`):** Gọi `provider.generate_reply()` bên ngoài DB transaction; mỗi tool call tự mở và đóng short-lived session riêng qua `_default_tool_session_factory()`.
- **Phase 3 (`service.py:192-294`):** Cập nhật `ai_turns`, `ai_usage_records`, thêm `ai_messages (ASSISTANT)` và `ai_tool_executions`, rồi `session.commit()`.

## 6. Test Results (trên working tree hardening ngày 2026-11-28)
- **Ruff check & format:** PASS (`All checks passed!`, 11 files checked/formatted).
- **Backend ordinary tests (`pytest -p no:cacheprovider -m "not integration" -q`):** PASS — `253 passed, 74 deselected` (bao gồm Alembic `20261026_01 -> 20261128_01` upgrade/downgrade parity, metadata parity `21` unique constraints, và test `AI-03` `retry_options.attempts == 1`).
- **Frontend JS (`node --check frontend/js/app.js` & `node --test frontend/js/app.test.js`):** PASS — `30 passed, 0 failed`.
- **MySQL 8.4.4 integration (`74` tests) & Docker build:** **NOT RUN / NOT VERIFIED** trên bản hardening 2026-11-28 do Docker Desktop daemon đang tắt (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.`).
- **Lưu ý:** Chưa test Gemini live API với `GEMINI_API_KEY` thật.

## 7. Independent Review Findings & Hardening Status
1. **AI-01 [Fixed in code, pending MySQL run — P1 / High]:** Khởi tạo `lease_expires_at` (`request_deadline_seconds + 15s` UTC) và `lease_generation=1`; recovery atomic trong Phase 1 dưới lock `ai_conversations` + current read `ai_turns` (`FOR UPDATE`); fencing Phase 3 bằng `claim_turn_completion()` (`WHERE id=? AND status='RUNNING' AND lease_generation=?`); catch-all `except Exception:` ghi `AI_INTERNAL_ERROR`.
2. **AI-02 [Fixed in code, pending MySQL run — P2 / Medium]:**
   - **New conversation idempotency:** Migration tăng dần `20261128_01_ai_conversation_create_key.py` thêm `ai_conversations.create_request_key BINARY(16) NULL` + `uq_ai_conversation_create_request (owner_user_id, create_request_key)`. Hai request đồng thời/tuần tự tạo mới cùng key được serialize và bảo vệ bằng DB unique constraint.
   - **Retry semantics:** Same key + same payload + `SUCCEEDED` → replay response đã lưu; `RUNNING` → `409 AIConversationConflictError`; `FAILED` → trả lại trạng thái lỗi đã lưu (`AIProviderTimeoutError`/`AIToolBudgetExceededError`/`AIToolValidationError`/`AIProviderUnavailableError`) mà không chạy lại provider; khác payload → `409`. Frontend giữ nguyên `client_request_key` khi gặp network error (mất response) và tạo key mới khi explicit retry sau HTTP error từ server.
3. **AI-03 [Verified & Fixed — P2 / Medium]:** Đã kiểm chứng `google-genai==1.75.0` trong `.venv`: `GenerateContentConfig.http_options` hỗ trợ `HttpOptions(timeout=..., retry_options=...)` với `timeout` tính bằng **milliseconds** và `BaseApiClient._request` mặc định dùng `self._retry` nếu không truyền `retry_options`. Đã cấu hình `timeout=remaining_ms` theo `ToolBudget.remaining_seconds()` và `retry_options=HttpRetryOptions(attempts=1)` ở mỗi round; dừng trước round mới khi `remaining_seconds <= 0`. (Vẫn phụ thuộc blocking HTTP socket timeout ở OS/httpx khi gọi live API).
4. **AI-04 [Assessed — No issue found, pending MySQL run]:** `session.commit()` ở cuối Phase 1 kết thúc transaction (`session.in_transaction() == False`).
5. **AI-05 [Deferred — P3 / Low]:** Chưa log `finish_reason` khi Gemini trả về text rỗng / safety block.
6. **AI-06 [Fixed & Verified — P2 / Medium]:** `resetAiUiState()` + `AbortController` trong `replaceSession()` / `invalidateSession()` xóa state, DOM và hủy/bỏ qua response trễ từ phiên cũ.
7. **AI-07 [Deferred — P3 / Low]:** Chưa chạy smoke test với Gemini live API thật.

## 8. Những rủi ro chưa xác minh
- Bộ 72 MySQL 8.4.4 integration tests (gồm 4 test mới cho AI-01/AI-02/AI-04) và `docker build` chưa chạy được trên bản hardening 2026-11-28 vì Docker Desktop daemon đang tắt (`dockerDesktopLinuxEngine` unavailable).
- Tương thích schema `types.FunctionDeclaration` / `types.Part.from_function_response` và `GenerateContentConfig.http_options` với Gemini API live endpoint (`GEMINI_API_KEY` thật).
- Idempotency cho concurrent requests tạo conversation mới (`conversation_id=None`) nếu không có migration bổ sung `ai_conversations.create_request_key`.

## 9. Thứ tự công việc agent tiếp theo cần xử lý
1. Sửa **AI-01 (P1)**: set `lease_expires_at` khi tạo `AITurn`, bổ sung catch-all `except Exception:` trong Phase 2 để đóng turn/usage khi gặp lỗi bất ngờ, và thêm stale-lease recovery trong Phase 1 kèm integration test trên MySQL.
2. Xử lý **AI-02** (idempotency theo `client_request_key` nếu Owner duyệt trong V1) và **AI-06** (reset `aiUiState` khi logout).
3. Chạy lại full ordinary + MySQL integration + Ruff + JS tests sau khi sửa, rồi mới push & mở PR vào `main`.
4. Trước khi demo chính thức: chạy 1 smoke test thủ công với `AI_PROVIDER=gemini` và `GEMINI_API_KEY` thật.

## 10. Những phần chưa cần làm hoặc nằm ngoài SCMS V1
- RAG, vector database, multi-agent orchestration.
- Write tools / AI tự động tạo event hoặc sửa task.
- Distributed worker queue (Celery/RQ) hoặc Redis locks cho AI turn.
- Billing/cost reconciliation tự động theo bảng giá Gemini.
