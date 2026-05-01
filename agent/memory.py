"""AgentCore Memory setup for the Expense Tracker agent.

Provides short-term memory (session context for multi-turn conversations)
and long-term semantic memory (fact extraction across sessions).

Usage:
    # One-time setup (run once to create the memory resource):
    python memory.py --create

    # In the agent, use get_session_manager() to get a configured session manager.
"""

import os
import logging

from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

logger = logging.getLogger(__name__)

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")

# Set after create_memory_resource() or via environment variable
MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")


def create_memory_resource():
    """One-time setup: create the AgentCore Memory resource with strategies.

    Run this once to provision the memory store. Save the returned memory ID
    in the AGENTCORE_MEMORY_ID environment variable for the agent to use.

    Returns:
        str: The memory resource ID.
    """
    client = MemoryClient(region_name=BEDROCK_REGION)

    memory = client.create_memory_and_wait(
        name="ExpenseTrackerMemory",
        description="Memory for the Expense Tracker chat agent — stores session context and learned facts",
        strategies=[
            {
                "summaryMemoryStrategy": {
                    "name": "SessionSummarizer",
                    "namespaces": ["/summaries/{actorId}/{sessionId}"],
                }
            },
            {
                "semanticMemoryStrategy": {
                    "name": "FactExtractor",
                    "namespaces": ["/facts/{actorId}"],
                }
            },
        ],
    )

    memory_id = memory.get("id")
    logger.info(f"Created AgentCore Memory resource: {memory_id}")
    return memory_id


def get_session_manager(session_id: str, actor_id: str = "default_user"):
    """Create an AgentCoreMemorySessionManager for a chat session.

    Args:
        session_id: Unique identifier for this conversation session.
        actor_id: Identifier for the user (defaults to "default_user" since
                  the app currently has no auth).

    Returns:
        AgentCoreMemorySessionManager configured with short-term and
        long-term memory retrieval.
    """
    if not MEMORY_ID:
        raise ValueError(
            "AGENTCORE_MEMORY_ID environment variable is not set. "
            "Run `python memory.py --create` first to provision the memory resource."
        )

    config = AgentCoreMemoryConfig(
        memory_id=MEMORY_ID,
        session_id=session_id,
        actor_id=actor_id,
        retrieval_config={
            "/facts/{actorId}": RetrievalConfig(
                top_k=10,
                relevance_score=0.5,
            ),
            "/summaries/{actorId}/{sessionId}": RetrievalConfig(
                top_k=5,
                relevance_score=0.5,
            ),
        },
    )

    return AgentCoreMemorySessionManager(
        agentcore_memory_config=config,
        region_name=BEDROCK_REGION,
    )


if __name__ == "__main__":
    import sys

    if "--create" in sys.argv:
        mid = create_memory_resource()
        print(f"Memory ID: {mid}")
        print(f"Set this in your environment: export AGENTCORE_MEMORY_ID={mid}")
    else:
        print("Usage: python memory.py --create")
        print("  Creates the AgentCore Memory resource (one-time setup).")
