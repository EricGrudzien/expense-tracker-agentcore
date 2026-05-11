#!/usr/bin/env python3
"""Tear down AgentCore resources (Memory + Runtime) using boto3.

Reads resource IDs from .agentcore-state.json (created by deploy_agentcore.py).

Usage:
    python teardown_agentcore.py [--delete-memory] [--delete-runtime] [--all]

Environment variables:
    AWS_REGION — AWS region (default: us-east-1)
"""

import argparse
import json
import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
STATE_FILE = os.path.join(os.path.dirname(__file__), ".agentcore-state.json")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def delete_memory():
    """Delete the AgentCore Memory resource."""
    print("\n── Deleting AgentCore Memory ──────────────────────────────────")

    state = load_state()
    memory_id = state.get("memory_id")

    if not memory_id:
        print("  No memory_id found in state file. Nothing to delete.")
        return

    from bedrock_agentcore.memory import MemoryClient

    client = MemoryClient(region_name=REGION)

    try:
        client.delete_memory(memory_id=memory_id)
        print(f"  ✓ Memory deleted: {memory_id}")
        del state["memory_id"]
        save_state(state)
    except Exception as e:
        print(f"  ✗ Failed to delete memory: {e}")


def delete_runtime():
    """Delete the AgentCore Runtime agent."""
    print("\n── Deleting AgentCore Runtime ─────────────────────────────────")

    state = load_state()
    agent_runtime_arn = state.get("agent_runtime_arn")

    if not agent_runtime_arn:
        print("  No agent_runtime_arn found in state file. Nothing to delete.")
        return

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    try:
        client.delete_agent_runtime(agentRuntimeArn=agent_runtime_arn)
        print(f"  ✓ Runtime deletion initiated: {agent_runtime_arn}")
        # Remove from state
        del state["agent_runtime_arn"]
        if "agent_runtime_endpoint" in state:
            del state["agent_runtime_endpoint"]
        save_state(state)
    except Exception as e:
        print(f"  ✗ Failed to delete runtime: {e}")


def main():
    parser = argparse.ArgumentParser(description="Tear down AgentCore resources")
    parser.add_argument("--delete-memory", action="store_true", help="Delete AgentCore Memory")
    parser.add_argument("--delete-runtime", action="store_true", help="Delete AgentCore Runtime")
    parser.add_argument("--all", action="store_true", help="Delete both Memory and Runtime")
    args = parser.parse_args()

    if not any([args.delete_memory, args.delete_runtime, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.all or args.delete_runtime:
        delete_runtime()

    if args.all or args.delete_memory:
        delete_memory()

    print("\n── Done ──────────────────────────────────────────────────────")

    # Clean up state file if empty
    state = load_state()
    if not state:
        os.remove(STATE_FILE)
        print("  State file removed (all resources cleaned up).")


if __name__ == "__main__":
    main()
