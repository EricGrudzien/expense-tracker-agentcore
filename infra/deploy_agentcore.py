#!/usr/bin/env python3
"""Deploy AgentCore resources (Memory + Runtime) using boto3.

These resources don't have CloudFormation support yet, so we manage them
via the SDK. Run this AFTER the CloudFormation stack is deployed.

Usage:
    python deploy_agentcore.py [--create-memory] [--create-runtime] [--all]

Environment variables:
    AWS_REGION          — AWS region (default: us-east-1)
    ECR_IMAGE_URI       — Full ECR image URI for the agent container
    AGENT_RUNTIME_ROLE  — IAM role ARN for AgentCore Runtime (from CFN output)
"""

import argparse
import json
import os
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
PREFIX = "egru"
TAGS = {"user": "egru"}

# File to persist resource IDs between deploy/teardown
STATE_FILE = os.path.join(os.path.dirname(__file__), ".agentcore-state.json")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  State saved to {STATE_FILE}")


def create_memory():
    """Create the AgentCore Memory resource with STM + LTM strategies."""
    print("\n── Creating AgentCore Memory ──────────────────────────────────")

    from bedrock_agentcore.memory import MemoryClient

    client = MemoryClient(region_name=REGION)

    memory = client.create_memory_and_wait(
        name=f"{PREFIX}-expense-tracker-memory",
        description="Memory for the Expense Tracker agent — session context and semantic facts",
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
    print(f"  ✓ Memory created: {memory_id}")
    print(f"  Set env var: export AGENTCORE_MEMORY_ID={memory_id}")

    state = load_state()
    state["memory_id"] = memory_id
    save_state(state)

    return memory_id


def create_runtime():
    """Create the AgentCore Runtime agent."""
    print("\n── Creating AgentCore Runtime ─────────────────────────────────")

    ecr_image_uri = os.environ.get("ECR_IMAGE_URI")
    role_arn = os.environ.get("AGENT_RUNTIME_ROLE")

    if not ecr_image_uri:
        print("  ERROR: ECR_IMAGE_URI environment variable is required.")
        print("  Set it to the full ECR image URI (from CFN output + tag).")
        print("  Example: 905418197933.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent:latest")
        sys.exit(1)

    if not role_arn:
        print("  ERROR: AGENT_RUNTIME_ROLE environment variable is required.")
        print("  Get it from the CloudFormation stack output: AgentRuntimeRoleArn")
        sys.exit(1)

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    response = client.create_agent_runtime(
        agentRuntimeName=f"{PREFIX}-expense-agent",
        agentRuntimeArtifact={
            "containerConfiguration": {
                "containerUri": ecr_image_uri,
            }
        },
        networkConfiguration={"networkMode": "PUBLIC"},
        roleArn=role_arn,
    )

    agent_runtime_arn = response.get("agentRuntimeArn")
    print(f"  ✓ Runtime created: {agent_runtime_arn}")
    print(f"  Status: {response.get('status', 'CREATING')}")

    state = load_state()
    state["agent_runtime_arn"] = agent_runtime_arn
    save_state(state)

    # Wait for it to become active
    print("  Waiting for runtime to become ACTIVE...")
    for i in range(60):
        time.sleep(10)
        try:
            status_resp = client.get_agent_runtime(agentRuntimeArn=agent_runtime_arn)
            status = status_resp.get("status", "UNKNOWN")
            if status == "ACTIVE":
                print(f"  ✓ Runtime is ACTIVE")
                endpoint = status_resp.get("agentRuntimeEndpoint", "")
                if endpoint:
                    state["agent_runtime_endpoint"] = endpoint
                    save_state(state)
                    print(f"  Endpoint: {endpoint}")
                return agent_runtime_arn
            elif status in ("FAILED", "DELETING"):
                print(f"  ✗ Runtime failed with status: {status}")
                sys.exit(1)
            else:
                print(f"  ... status: {status} ({(i+1)*10}s)")
        except Exception as e:
            print(f"  ... waiting ({e})")

    print("  ⚠ Timed out waiting for ACTIVE status. Check the console.")
    return agent_runtime_arn


def main():
    parser = argparse.ArgumentParser(description="Deploy AgentCore resources")
    parser.add_argument("--create-memory", action="store_true", help="Create AgentCore Memory")
    parser.add_argument("--create-runtime", action="store_true", help="Create AgentCore Runtime")
    parser.add_argument("--all", action="store_true", help="Create both Memory and Runtime")
    args = parser.parse_args()

    if not any([args.create_memory, args.create_runtime, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.all or args.create_memory:
        create_memory()

    if args.all or args.create_runtime:
        create_runtime()

    print("\n── Done ──────────────────────────────────────────────────────")
    print(f"  State file: {STATE_FILE}")


if __name__ == "__main__":
    main()
