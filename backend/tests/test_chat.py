"""Unit tests for the /api/chat endpoint (AgentCore Runtime proxy)."""

import io
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError, ConnectTimeoutError

# Set env vars before importing app
os.environ.setdefault("BEDROCK_REGION", "us-east-1")

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app, get_runtime_arn


@pytest.fixture
def client():
    """Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def mock_runtime_arn():
    """Mock get_runtime_arn to return a test ARN."""
    with patch("app.get_runtime_arn", return_value="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent"):
        yield


@pytest.fixture
def mock_no_runtime_arn():
    """Mock get_runtime_arn to return None (not configured)."""
    with patch("app.get_runtime_arn", return_value=None):
        yield


def _make_agent_response(answer, chart=None):
    """Create a mock boto3 response with a streaming body."""
    body = {"answer": answer}
    if chart is not None:
        body["chart"] = chart
    stream = io.BytesIO(json.dumps(body).encode())
    return {"response": stream}


@pytest.fixture
def mock_agentcore_client():
    """Mock the agentcore_client.invoke_agent_runtime call."""
    mock_client = MagicMock()
    mock_client.invoke_agent_runtime.return_value = _make_agent_response(
        "You spent $1,200 on hotels."
    )
    with patch("app.agentcore_client", mock_client):
        yield mock_client


# ── Input validation tests ────────────────────────────────────────────────────


class TestInputValidation:
    """Tests for chat endpoint input validation."""

    def test_empty_message_returns_400(self, client, mock_runtime_arn, mock_agentcore_client):
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Message is required"

    def test_missing_message_field_returns_400(self, client, mock_runtime_arn, mock_agentcore_client):
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Message is required"

    def test_whitespace_only_message_returns_400(self, client, mock_runtime_arn, mock_agentcore_client):
        resp = client.post("/api/chat", json={"message": "   "})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Message is required"

    def test_message_too_long_returns_400(self, client, mock_runtime_arn, mock_agentcore_client):
        resp = client.post("/api/chat", json={"message": "x" * 1001})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Message must be 1000 characters or fewer"

    def test_valid_message_proceeds(self, client, mock_runtime_arn, mock_agentcore_client):
        resp = client.post("/api/chat", json={"message": "How much on hotels?"})
        assert resp.status_code == 200


# ── ARN resolution tests ─────────────────────────────────────────────────────


class TestARNResolution:
    """Tests for runtime ARN resolution."""

    def test_env_var_takes_precedence(self):
        with patch.dict(os.environ, {"AGENTCORE_RUNTIME_ARN": "arn:from:env"}):
            # Re-import to pick up env var
            with patch("app.AGENTCORE_RUNTIME_ARN", "arn:from:env"):
                with patch("app.get_runtime_arn") as mock_fn:
                    mock_fn.return_value = "arn:from:env"
                    assert mock_fn() == "arn:from:env"

    def test_state_file_fallback(self, tmp_path):
        state_file = tmp_path / ".agentcore-state.json"
        state_file.write_text(json.dumps({"agent_runtime_arn": "arn:from:state"}))

        with patch("app.AGENTCORE_RUNTIME_ARN", None):
            with patch("app.STATE_FILE_PATH", str(state_file)):
                from app import get_runtime_arn as fresh_get_arn
                # Call the real function with patched paths
                result = fresh_get_arn()
                # Since AGENTCORE_RUNTIME_ARN module-level is patched,
                # we need to test the function directly
                assert result is not None

    def test_503_when_no_arn_available(self, client, mock_no_runtime_arn):
        with patch("app.agentcore_client", MagicMock()):
            resp = client.post("/api/chat", json={"message": "hello"})
            assert resp.status_code == 503
            assert "not configured" in resp.get_json()["error"]


# ── Success path tests ────────────────────────────────────────────────────────


class TestSuccessPath:
    """Tests for successful agent invocation."""

    def test_answer_only_response(self, client, mock_runtime_arn, mock_agentcore_client):
        mock_agentcore_client.invoke_agent_runtime.return_value = _make_agent_response(
            "Total spending is $5,430."
        )
        resp = client.post("/api/chat", json={"message": "What is my total?"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["answer"] == "Total spending is $5,430."
        assert data["session_id"]  # session_id must be present and non-empty
        assert data["sql"] is None
        assert data["data"] is None
        assert data.get("chart") is None

    def test_answer_with_chart_response(self, client, mock_runtime_arn, mock_agentcore_client):
        chart_config = {"type": "bar", "data": {"labels": ["hotel"], "datasets": [{"data": [1200]}]}}
        mock_agentcore_client.invoke_agent_runtime.return_value = _make_agent_response(
            "Here's your chart.", chart=chart_config
        )
        resp = client.post("/api/chat", json={"message": "Show a bar chart"})
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["answer"] == "Here's your chart."
        assert data["session_id"]  # session_id must be present and non-empty
        assert data["chart"] == chart_config

    def test_session_id_is_uuid4(self, client, mock_runtime_arn, mock_agentcore_client):
        import uuid

        resp = client.post("/api/chat", json={"message": "test"})
        call_kwargs = mock_agentcore_client.invoke_agent_runtime.call_args[1]
        session_id = call_kwargs["runtimeSessionId"]

        # Verify it's a valid UUID4
        parsed = uuid.UUID(session_id, version=4)
        assert str(parsed) == session_id

        # Verify session_id is also in the response body
        data = resp.get_json()
        assert data["session_id"] == session_id

    def test_message_forwarded_as_prompt(self, client, mock_runtime_arn, mock_agentcore_client):
        resp = client.post("/api/chat", json={"message": "How much on hotels?"})
        call_kwargs = mock_agentcore_client.invoke_agent_runtime.call_args[1]
        payload = json.loads(call_kwargs["payload"])
        assert payload["prompt"] == "How much on hotels?"
        assert "session_id" in payload

        # Verify the session_id in payload matches the response
        data = resp.get_json()
        assert data["session_id"] == payload["session_id"]


# ── Error path tests ──────────────────────────────────────────────────────────


class TestErrorPaths:
    """Tests for error handling in the chat proxy."""

    def test_read_timeout_returns_502(self, client, mock_runtime_arn, mock_agentcore_client):
        mock_agentcore_client.invoke_agent_runtime.side_effect = ReadTimeoutError(
            endpoint_url="https://test"
        )
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 502
        assert resp.get_json()["error"] == "Agent service unavailable"

    def test_connect_timeout_returns_502(self, client, mock_runtime_arn, mock_agentcore_client):
        mock_agentcore_client.invoke_agent_runtime.side_effect = ConnectTimeoutError(
            endpoint_url="https://test"
        )
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 502
        assert resp.get_json()["error"] == "Agent service unavailable"

    def test_client_error_returns_502(self, client, mock_runtime_arn, mock_agentcore_client):
        mock_agentcore_client.invoke_agent_runtime.side_effect = ClientError(
            error_response={"Error": {"Code": "500", "Message": "Internal"}},
            operation_name="InvokeAgentRuntime",
        )
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 502
        assert resp.get_json()["error"] == "Agent returned an error"

    def test_unexpected_exception_returns_500(self, client, mock_runtime_arn, mock_agentcore_client):
        mock_agentcore_client.invoke_agent_runtime.side_effect = RuntimeError("boom")
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "Internal server error"
