# Implementation Plan: AgentCore Memory Multi-Turn

## Overview

Integrate AgentCore Memory into the Expense Tracker agent for multi-turn conversations. The implementation progresses from backend infrastructure (memory module fixes, agent per-request pattern) through Flask session propagation, to frontend session tracking and UI updates. Each step builds on the previous, with tests validating session ID flow at each layer.

## Tasks

- [x] 1. Fix memory module and add graceful degradation
  - [x] 1.1 Update `agent/memory.py` — fix namespace trailing slashes and add graceful degradation
    - Fix namespace keys in `retrieval_config` to include trailing slashes: `/facts/{actorId}/` and `/summaries/{actorId}/{sessionId}/`
    - Fix namespace values in `create_memory_resource()` strategies to include trailing slashes
    - Change `get_session_manager()` to return `None` instead of raising `ValueError` when `MEMORY_ID` is empty
    - Add a `logger.warning()` when `MEMORY_ID` is not set
    - _Requirements: 2.1, 2.5_

  - [x] 1.2 Update `agent/requirements.txt` — ensure memory dependencies are listed
    - Verify `bedrock-agentcore` is present (already listed, confirm it includes memory sub-package)
    - Add `bedrock-agentcore[memory]` if the memory extras are a separate install target, or confirm the base package includes memory
    - _Requirements: 2.1_

- [x] 2. Implement per-request Agent creation in agent entrypoint
  - [x] 2.1 Refactor `agent/agent.py` — per-request Agent with session_manager
    - Add `import logging` and create a module-level logger
    - Import `get_session_manager` from `memory`
    - Add `MEMORY_ENABLED = bool(os.environ.get("AGENTCORE_MEMORY_ID"))` flag
    - Keep `model`, `system_prompt`, and `tools` at module level (stateless, reusable)
    - Create a module-level `agent_no_memory` Agent instance for the fallback path
    - Refactor `invoke()` to: extract `session_id` from payload, create per-request `Agent` with `session_manager` when memory is enabled, fall back to `agent_no_memory` otherwise
    - Use `get_session_manager()` as a context manager (`with ... as session_manager`)
    - Return `{"answer": str(result), "session_id": session_id}` from invoke
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 7.1, 7.2, 7.3_

  - [x] 2.2 Update `infra/Dockerfile` — pass `AGENTCORE_MEMORY_ID` env var through
    - Add `ENV AGENTCORE_MEMORY_ID=""` placeholder so the variable is defined in the container
    - The actual value is injected at runtime by AgentCore; this ensures the variable key exists
    - _Requirements: 2.1_

- [x] 3. Checkpoint — Ensure agent changes are consistent
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Update Flask backend for session ID propagation
  - [x] 4.1 Modify `/api/chat` endpoint in `backend/app.py` — accept and forward session_id
    - Extract `session_id` from request JSON body (`data.get("session_id")`)
    - If missing or empty, generate a UUID v4 as fallback
    - Pass `session_id` as `runtimeSessionId` to `invoke_agent_runtime()`
    - Include `session_id` in the payload sent to the agent: `{"prompt": message, "session_id": session_id}`
    - Include `session_id` in the JSON response to the frontend
    - _Requirements: 3.3, 3.4, 4.1, 4.2, 4.3_

  - [ ]* 4.2 Write property tests for session ID passthrough (Hypothesis)
    - **Property 1: Session ID passthrough invariant** — for any valid UUID string provided as `session_id` in the request body, the Flask endpoint passes that exact value as `runtimeSessionId` to the AgentCore client
    - **Validates: Requirements 3.3, 4.1**
    - **Property 2: Response always contains session_id** — for any POST to `/api/chat` (with or without `session_id` field), the response body contains a `session_id` field with a valid UUID v4
    - **Validates: Requirements 4.3**
    - Add tests to `backend/tests/test_chat.py` using `@given(st.uuids())` and `@settings(max_examples=100)`
    - _Requirements: 3.3, 3.4, 4.1, 4.2, 4.3_

  - [ ]* 4.3 Write unit tests for session_id handling in Flask
    - Test: request with `session_id` field uses that value (not generates a new one)
    - Test: request without `session_id` field generates a valid UUID v4
    - Test: response always contains `session_id` matching the one used in the invocation
    - Test: `session_id` is included in the agent payload
    - Add to `backend/tests/test_chat.py`
    - _Requirements: 3.3, 3.4, 4.1, 4.2, 4.3_

- [x] 5. Checkpoint — Ensure backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Update frontend for session tracking and new conversation
  - [x] 6.1 Update `frontend/chat.js` — add session_id generation and send with messages
    - Generate `sessionId = crypto.randomUUID()` at module level (page load)
    - Include `session_id: sessionId` in the `fetch()` body of `sendMessage()`
    - On response, do not overwrite local `sessionId` (keep using the locally-generated one unless response confirms a different value)
    - _Requirements: 3.1, 3.2, 6.2_

  - [x] 6.2 Update `frontend/chat.js` — add "New Conversation" functionality
    - Add `startNewConversation()` function: regenerate `sessionId`, clear `messagesEl` DOM, re-render welcome message
    - Wire the function to a "New Conversation" button (added in 6.3)
    - _Requirements: 5.2, 5.3, 5.4_

  - [x] 6.3 Update `frontend/chat.html` — add "New Conversation" button to chat card header
    - Add a button element inside `.chat-card-header` next to the title
    - Style with existing design system (indigo outline or secondary style)
    - Wire `onclick` to `startNewConversation()`
    - _Requirements: 5.1_

  - [x] 6.4 Update `frontend/chat.js` — improve scroll behavior
    - Track whether user has scrolled up (via `scroll` event listener on `messagesEl`)
    - Only auto-scroll to bottom if user is near the bottom (within ~50px threshold)
    - Always auto-scroll when a new user message is sent
    - _Requirements: 6.3_

- [x] 7. Checkpoint — Ensure frontend changes are consistent
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Integration wiring and final verification
  - [x] 8.1 Update existing tests in `backend/tests/test_chat.py` — adapt to new response shape
    - Update assertions to expect `session_id` in response JSON
    - Update `_make_agent_response()` helper to include `session_id` in mock body if needed
    - Verify existing tests still pass with the new `session_id` field in response
    - _Requirements: 4.3_

  - [ ]* 8.2 Write property test for session manager configuration (Hypothesis)
    - **Property 3: Session manager configured with request session_id** — for any valid session_id string, calling `get_session_manager(session_id)` produces a session manager whose config `session_id` equals the input
    - **Validates: Requirements 2.1**
    - Add to a new file `backend/tests/test_memory.py` or alongside agent tests
    - Mock `AgentCoreMemorySessionManager` and verify the config passed to it
    - _Requirements: 2.1_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Frontend has no automated test framework — UI changes are validated manually or via future Playwright integration
- The deploy script (`infra/deploy_agentcore.py`) already supports `--create-memory` and does not need code changes (Requirement 1 is already fulfilled)
- Docker build/deploy are manual steps performed by the developer after code changes

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["4.1", "6.1", "6.3"] },
    { "id": 3, "tasks": ["4.2", "4.3", "6.2", "6.4"] },
    { "id": 4, "tasks": ["8.1"] },
    { "id": 5, "tasks": ["8.2"] }
  ]
}
```
