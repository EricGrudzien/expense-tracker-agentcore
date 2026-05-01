"""Expense Tracker Strands Agent — deployed on AgentCore Runtime.

This agent answers natural-language questions about expense data by using
structured tools (no raw SQL generation). It is designed to be deployed
on Amazon Bedrock AgentCore Runtime via BedrockAgentCoreApp.
"""

import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel

from tools import query_expenses, get_summary, chart_builder

# ── Configuration ─────────────────────────────────────────────────────────────

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
BEDROCK_MODEL = os.environ.get(
    "BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "system.txt")

# ── Load system prompt ────────────────────────────────────────────────────────

with open(PROMPT_PATH, "r") as f:
    system_prompt = f.read()

# ── Create the agent ──────────────────────────────────────────────────────────

model = BedrockModel(
    model_id=BEDROCK_MODEL,
    region_name=BEDROCK_REGION,
    temperature=0,
    max_tokens=1024,
)

agent = Agent(
    model=model,
    system_prompt=system_prompt,
    tools=[query_expenses, get_summary, chart_builder],
    callback_handler=None,  # No console output when running as a service
)

# ── AgentCore Runtime app ─────────────────────────────────────────────────────

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    """Process a chat message and return the agent's response."""
    user_message = payload.get("prompt", payload.get("message", "Hello"))
    result = agent(user_message)
    return {"answer": str(result)}


if __name__ == "__main__":
    app.run()
