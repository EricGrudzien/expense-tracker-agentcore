"""Expense Tracker Strands Agent — deployed on AgentCore Runtime.

This agent answers natural-language questions about expense data by using
structured tools (no raw SQL generation). It is designed to be deployed
on Amazon Bedrock AgentCore Runtime via BedrockAgentCoreApp.

The Agent is created per-request when memory is enabled because the
session_manager is tied to a specific session_id and is passed to the
Agent constructor. model, system_prompt, and tools stay module-level
since they are stateless and reusable.
"""

import logging
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel

from memory import get_session_manager
from tools import query_expenses, get_summary, chart_builder

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
BEDROCK_MODEL = os.environ.get(
    "BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
MEMORY_ENABLED = bool(os.environ.get("AGENTCORE_MEMORY_ID"))

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "system.txt")

# ── Load system prompt ────────────────────────────────────────────────────────

with open(PROMPT_PATH, "r") as f:
    system_prompt = f.read()

# ── Stateless, reusable components ───────────────────────────────────────────

model = BedrockModel(
    model_id=BEDROCK_MODEL,
    region_name=BEDROCK_REGION,
    temperature=0,
    max_tokens=1024,
)

tools = [query_expenses, get_summary, chart_builder]

# ── Fallback agent (no memory) ────────────────────────────────────────────────

agent_no_memory = Agent(
    model=model,
    system_prompt=system_prompt,
    tools=tools,
    callback_handler=None,
)

# ── AgentCore Runtime app ─────────────────────────────────────────────────────

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    """Process a chat message and return the agent's response.

    When memory is enabled, creates a per-request Agent with a session_manager
    bound to the request's session_id. Falls back to the stateless
    agent_no_memory singleton otherwise.
    """
    user_message = payload.get("prompt", payload.get("message", "Hello"))
    session_id = payload.get("session_id", "ephemeral")

    if MEMORY_ENABLED:
        session_manager = get_session_manager(session_id)
        if session_manager is not None:
            with session_manager:
                agent = Agent(
                    model=model,
                    system_prompt=system_prompt,
                    tools=tools,
                    session_manager=session_manager,
                    callback_handler=None,
                )
                result = agent(user_message)
            return {"answer": str(result), "session_id": session_id}

    # Fallback: memory not enabled or get_session_manager returned None
    logger.warning("Running without memory (AGENTCORE_MEMORY_ID not set or unavailable)")
    result = agent_no_memory(user_message)
    return {"answer": str(result), "session_id": session_id}


if __name__ == "__main__":
    app.run()
