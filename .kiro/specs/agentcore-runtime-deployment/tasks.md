# Implementation Plan: AgentCore Runtime Deployment

## Overview

Wire the Flask `/api/chat` endpoint to invoke the Strands Agent deployed on Amazon Bedrock AgentCore Runtime. This involves replacing the placeholder chat endpoint with a real boto3 invocation, adding configuration resolution (env var → state file fallback), proper error handling, startup validation, and comprehensive tests.

## Tasks

- [x] 1. Add AgentCore Runtime configuration and client setup
  - [x] 1.1 Add configuration constants and ARN resolution to `backend/app.py`
    - Add `AGENTCORE_RUNTIME_ARN` env var lookup
    - Add `STATE_FILE_PATH` pointing to `infra/.agentcore-state.json`
    - Implement `get_runtime_arn()` function (env var → state file fallback)
    - Add boto3 client for `bedrock-agentcore` with timeout config (read_timeout=90, connect_timeout=10, retries max_attempts=1)
    - Add required imports: `uuid`, `botocore.config.Config`, `botocore.exceptions.ClientError`, `botocore.exceptions.ReadTimeoutError`, `botocore.exceptions.ConnectTimeoutError`
    - _Requirements: 6.1, 6.2, 6.4_

  - [x] 1.2 Add startup validation warning
    - At Flask startup (in the `if __name__ == "__main__"` block), call `get_runtime_arn()` and log a warning if no ARN is available
    - Warning message: "AGENTCORE_RUNTIME_ARN not set and state file not found. Chat endpoint will return 503 until configured."
    - _Requirements: 6.3_

- [x] 2. Implement the chat proxy endpoint
  - [x] 2.1 Replace the placeholder `/api/chat` endpoint with AgentCore Runtime invocation
    - Keep existing input validation (empty message → 400, message > 1000 chars → 400)
    - Resolve runtime ARN via `get_runtime_arn()`; return 503 if not configured
    - Generate a unique `runtimeSessionId` (UUID4) per request
    - Invoke `agentcore_client.invoke_agent_runtime()` with the ARN, session ID, and JSON payload `{"prompt": message}`
    - Parse the streaming response body as JSON
    - Extract `answer` and optional `chart` fields from the agent response
    - Return `{"answer": ..., "sql": null, "data": null, "chart": ...}` to the frontend
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.7, 5.3_

  - [x] 2.2 Add error handling for the chat proxy
    - Catch `ReadTimeoutError`, `ConnectTimeoutError`, `ConnectionError` → return 502 with `{"error": "Agent service unavailable"}`
    - Catch `ClientError` → log error, return 502 with `{"error": "Agent returned an error"}`
    - Catch generic `Exception` → log error, return 500 with `{"error": "Internal server error"}`
    - _Requirements: 3.4, 3.5, 5.5_

- [x] 3. Checkpoint - Verify chat proxy implementation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Write unit tests for the chat proxy
  - [x] 4.1 Create test file `backend/tests/test_chat.py` with pytest fixtures
    - Set up Flask test client fixture
    - Create mock for `get_runtime_arn()` returning a test ARN
    - Create mock for `agentcore_client.invoke_agent_runtime()` returning mock responses
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 4.2 Write unit tests for input validation
    - Test empty message returns 400 with "Message is required"
    - Test missing body returns 400
    - Test message > 1000 chars returns 400 with "Message must be 1000 characters or fewer"
    - Test valid message proceeds to invocation
    - _Requirements: 3.1_

  - [x] 4.3 Write unit tests for ARN resolution
    - Test env var takes precedence over state file
    - Test state file fallback when env var is not set
    - Test 503 response when neither env var nor state file provides ARN
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 4.4 Write unit tests for success path
    - Test agent returns answer only → response has answer, sql=null, data=null, chart=null
    - Test agent returns answer + chart → response includes chart config object
    - Test runtimeSessionId is a valid UUID4 format
    - _Requirements: 3.2, 3.3, 3.7, 5.3_

  - [x] 4.5 Write unit tests for error paths
    - Test ReadTimeoutError → 502 "Agent service unavailable"
    - Test ConnectTimeoutError → 502 "Agent service unavailable"
    - Test ClientError → 502 "Agent returned an error"
    - Test unexpected exception → 500 "Internal server error"
    - _Requirements: 3.4, 3.5, 5.5_

- [x] 5. Checkpoint - Ensure all unit tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 6. Write property-based tests for correctness properties
  - [ ]* 6.1 Write property test for message forwarding
    - **Property 1: Message forwarding preserves content**
    - Generate random valid messages (1–1000 chars, printable strings)
    - Mock the boto3 invocation and verify the payload contains the exact message as the `prompt` field
    - Use Hypothesis with `@settings(max_examples=100)`
    - **Validates: Requirements 3.1**

  - [ ]* 6.2 Write property test for response contract compliance
    - **Property 2: Response contract compliance**
    - Generate random agent responses (various answer strings, optional chart configs using dictionaries)
    - Verify the Chat Proxy response always contains exactly `answer`, `sql`, `data`, `chart` fields
    - Verify `sql` is always null, `data` is always null
    - Verify `answer` and `chart` are preserved unchanged from agent response
    - Use Hypothesis with `@settings(max_examples=100)`
    - **Validates: Requirements 3.2, 3.3, 5.3**

  - [ ]* 6.3 Write property test for session ID uniqueness
    - **Property 3: Session ID uniqueness**
    - Generate batches of N invocations (N between 2 and 50)
    - Capture all `runtimeSessionId` values passed to boto3
    - Verify all session IDs are unique (no duplicates in the batch)
    - Use Hypothesis with `@settings(max_examples=100)`
    - **Validates: Requirements 3.7**

  - [ ]* 6.4 Write property test for state file round-trip
    - **Property 4: State file persistence round-trip**
    - Generate random valid ARN strings and endpoint URLs
    - Write them to a temp state file in the expected format
    - Read them back via `get_runtime_arn()` and verify the ARN matches
    - Use Hypothesis with `@settings(max_examples=100)`
    - **Validates: Requirements 2.2**

- [x] 7. Add test dependencies to backend requirements
  - Add `pytest` and `hypothesis` to a `backend/requirements-dev.txt` file (or a test section)
  - Ensure tests can be run with `pytest backend/tests/`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.7_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The agent container (`agent/agent.py`) and deploy script (`infra/deploy_agentcore.py`) already exist and need no code changes
- Docker build, ECR push, and `deploy_agentcore.py` execution are manual developer steps — not coded tasks
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
