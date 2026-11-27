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

## 6. Test Results (trên code tại commit `2168953`)
- **Ruff check & format:** PASS (`All checks passed!`, `16 files already formatted`).
- **Backend ordinary tests (`pytest -p no:cacheprovider -m "not integration" -q`):** PASS — `250 passed, 68 deselected`.
- **MySQL 8.4.4 integration (`pytest -p no:cacheprovider -m integration --require-integration-env -q` trên 12 isolated schemas):** PASS — `68 passed, 250 deselected`.
- **Frontend JS (`node --check frontend/js/app.js` & `node --test frontend/js/app.test.js`):** PASS — `28 passed, 0 failed`.
- **Docker build (`docker build --file Dockerfile --tag scms-backend:day09-verify .`):** PASS.
- **Git diff check (`git diff --check`):** PASS.
- **Lưu ý:** Chưa test Gemini live API với `GEMINI_API_KEY` thật.

## 7. Independent Review Findings (Commit `2168953`)
1. **AI-01 (Confirmed Bug — P1 / High):** Process crash hoặc unhandled non-`AppException` trong Phase 2 làm `ai_turns` kẹt ở `RUNNING` (`inflight_guard=1`) với `lease_expires_at=None`, khiến `uq_ai_one_inflight_turn` khóa cứng conversation đó vĩnh viễn (`409 AIConversationConflictError`).
2. **AI-02 (Confirmed Bug / Gap — P2 / Medium):** `AIChatRequest` chưa nhận `client_request_key` / `Idempotency-Key`; `service.py:119` luôn sinh `uuid.uuid4().bytes` mới nên retry tạo duplicate turns.
3. **AI-03 (Potential Risk — P2 / Medium):** `GeminiAIProvider` cấu hình `HttpOptions.timeout` tĩnh cho mỗi HTTP call (`15s`) thay vì co lại theo thời gian còn lại của `ToolBudget` khi vòng lặp tool chạy nhiều round.
4. **AI-04 (Potential Risk — P2 / Medium):** `chat_with_assistant` tái sử dụng cùng một FastAPI `session` cho Phase 3 sau khi chờ provider; nên tách rõ lifecycle hoặc xử lý lỗi ghi Phase 3 để tránh kẹt turn.
5. **AI-05 (Improvement — P3 / Low):** Chưa log `finish_reason` khi Gemini trả về text rỗng / safety block.
6. **AI-06 (Improvement — P3 / Low):** Frontend chưa reset `aiUiState` khi đăng xuất (`invalidateSession`/`showSignedOut`).
7. **AI-07 (Potential Risk — P3 / Low):** Chưa chạy smoke test với Gemini live API thật.

## 8. Những rủi ro chưa xác minh
- Tương thích schema `types.FunctionDeclaration` / `types.Part.from_function_response` với Gemini API live endpoint (`GEMINI_API_KEY` thật).
- Hành vi connection pool dưới tải thực tế khi Gemini API phản hồi chậm sát ngưỡng timeout 15s.

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
