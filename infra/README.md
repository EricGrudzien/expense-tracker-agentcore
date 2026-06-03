# Infrastructure Deployment Guide

This directory contains everything needed to deploy and tear down the Expense Tracker
AgentCore infrastructure. All AWS resources are prefixed with `egru-` or `egru_` and
tagged with `user: egru`.

---

## Architecture Overview

```
CloudFormation Stack (egru-expense-agent-stack)
├── IAM Role: egru-expense-agent-runtime-role   (for AgentCore Runtime)
├── IAM Role: egru-chart-builder-lambda-role    (for Lambda)
├── ECR Repo: egru-expense-agent                (agent container image)
└── Lambda:   egru-chart-builder                (chart generation, code from S3)

boto3 Scripts (no CFN support yet)
├── AgentCore Memory: egru_expense_tracker_memory
└── AgentCore Runtime: egru_expense_agent

Local Containers
└── Flask Backend: egru-expense-backend         (docker, localhost:5000)
```

---

## Prerequisites

- AWS CLI configured with credentials (region: `us-east-1`)
- Python 3.10+ with `boto3` and `bedrock-agentcore` installed
- Docker (for building container images)
- S3 bucket `0-egru` exists (for Lambda deployment packages)

```bash
pip install boto3 bedrock-agentcore
```

---

## Full Deployment (Steps 1–6)

### Step 1: Upload Lambda Code to S3

The CloudFormation template pulls Lambda code from S3. Upload it first:

```bash
cd lambda/chart-builder
zip chart-builder.zip lambda_function.py
aws s3 cp chart-builder.zip s3://0-egru/cfn/lambdas/chart-builder.zip
rm chart-builder.zip
cd ../..
```

---

### Step 2: Deploy the CloudFormation Stack

Creates IAM roles, ECR repository, and chart-builder Lambda.

```bash
aws cloudformation deploy \
  --template-file infra/template.yaml \
  --stack-name egru-expense-agent-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1 \
  --tags user=egru
```

Get the outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name egru-expense-agent-stack \
  --query "Stacks[0].Outputs" \
  --output table \
  --region us-east-1
```

Note these values for later steps:
- `ECRRepositoryUri` — the ECR repo URI
- `AgentRuntimeRoleArn` — IAM role for the agent runtime

---

### Step 3: Build and Push the Agent Container Image

```bash
# Get your account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Build the image (from project root, linux/arm64 required by AgentCore)
docker build --platform linux/arm64 -f infra/Dockerfile -t egru-expense-agent .

# Tag and push
docker tag egru-expense-agent:latest \
  ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent:latest

docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent:latest
```

---

### Step 4: Deploy Agent to AgentCore Runtime

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

export ECR_IMAGE_URI=${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent:latest
export AGENT_RUNTIME_ROLE=arn:aws:iam::${AWS_ACCOUNT_ID}:role/egru-expense-agent-runtime-role

cd infra
python deploy_agentcore.py --create-runtime
```

The script creates the runtime and polls until status is `READY`. It saves the ARN to
`.agentcore-state.json`.

**Verify status manually:**
```bash
# Get the runtime ID from the state file
RUNTIME_ID=$(python3 -c "import json; print(json.load(open('.agentcore-state.json'))['agent_runtime_id'])")

aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id ${RUNTIME_ID} \
  --region us-east-1 \
  --query "status"
```

Expected output: `"READY"`

---

### Step 5: Build and Run the Flask Backend Container

```bash
cd ..  # back to project root

# Build the Flask container
docker build -t egru-expense-backend ./backend

# Get the runtime ARN from state
RUNTIME_ARN=$(python3 -c "import json; print(json.load(open('infra/.agentcore-state.json'))['agent_runtime_arn'])")

# Run with AWS credentials
docker run -p 5000:5000 \
  -e AGENTCORE_RUNTIME_ARN=${RUNTIME_ARN} \
  -e AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id) \
  -e AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key) \
  -e AWS_SESSION_TOKEN=$(aws configure get aws_session_token) \
  -e AWS_DEFAULT_REGION=us-east-1 \
  egru-expense-backend
```

---

### Step 6: Start the Frontend and Test

```bash
# In a new terminal
cd frontend
python3 -m http.server 8080
```

Open http://localhost:8080 and navigate to the Chat page.

**Test via curl:**
```bash
# Test CRUD (should work immediately)
curl http://localhost:5000/api/summary

# Test chat (goes through AgentCore)
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How much did I spend total?"}'
```

**Test agent directly via boto3:**
```bash
python3 -c "
import boto3, json
client = boto3.client('bedrock-agentcore', region_name='us-east-1')
resp = client.invoke_agent_runtime(
    agentRuntimeArn='$(python3 -c "import json; print(json.load(open('infra/.agentcore-state.json'))['agent_runtime_arn'])")',
    payload=json.dumps({'prompt': 'What categories do I have?'}).encode()
)
body = json.loads(resp['response'].read())
print(json.dumps(body, indent=2))
"
```

---

## Teardown (Complete Cleanup)

Tear down in reverse order:

```bash
# 1. Stop local Docker containers
docker stop $(docker ps -q --filter ancestor=egru-expense-backend)

# 2. Delete AgentCore resources (Runtime + Memory)
cd infra
python teardown_agentcore.py --all
cd ..

# 3. Delete the ECR images (required before stack deletion)
aws ecr batch-delete-image \
  --repository-name egru-expense-agent \
  --image-ids imageTag=latest \
  --region us-east-1

# 4. Delete the CloudFormation stack
aws cloudformation delete-stack \
  --stack-name egru-expense-agent-stack \
  --region us-east-1

# 5. Wait for stack deletion
aws cloudformation wait stack-delete-complete \
  --stack-name egru-expense-agent-stack \
  --region us-east-1

# 6. (Optional) Remove Lambda zip from S3
aws s3 rm s3://0-egru/cfn/lambdas/chart-builder.zip
```

---

## Gotchas and Lessons Learned

| Issue | Solution |
|-------|----------|
| AgentCore Runtime name can't have hyphens | Use underscores: `egru_expense_agent` |
| `get_agent_runtime` uses `agentRuntimeId` | But `invoke_agent_runtime` uses `agentRuntimeArn` — different APIs use different identifiers |
| Response body is at `resp['response']` | Not `resp['body']` — it's a `StreamingBody` that needs `.read()` |
| Agent response has `result` field | The Strands `BedrockAgentCoreApp` returns `{"result": "..."}` |
| Lambda code too large for inline CFN | Upload zip to S3, reference via `S3Bucket`/`S3Key` in template |
| CFN fails with `ResourceExistenceCheck` | A resource with that name already exists — delete it first or remove from template |
| Docker needs `--platform linux/arm64` | AgentCore Runtime requires ARM64 containers |

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `template.yaml` | CloudFormation template — IAM roles, ECR repo, Lambda (from S3) |
| `Dockerfile` | Agent container image definition (linux/arm64) |
| `deploy_agentcore.py` | Create AgentCore Memory + Runtime (boto3) |
| `teardown_agentcore.py` | Delete AgentCore Memory + Runtime (boto3) |
| `.agentcore-state.json` | Auto-generated — stores resource IDs (gitignored) |
| `README.md` | This file |

---

## Resource Naming Convention

| Resource | Name | Notes |
|----------|------|-------|
| CloudFormation Stack | `egru-expense-agent-stack` | |
| ECR Repository | `egru-expense-agent` | Hyphens OK in ECR |
| IAM Role (Runtime) | `egru-expense-agent-runtime-role` | Hyphens OK in IAM |
| IAM Role (Lambda) | `egru-chart-builder-lambda-role` | |
| Lambda Function | `egru-chart-builder` | Code from `s3://0-egru/cfn/lambdas/` |
| AgentCore Memory | `egru_expense_tracker_memory` | Underscores only |
| AgentCore Runtime | `egru_expense_agent` | Underscores only |
| Flask Container | `egru-expense-backend` | Local Docker only |

All AWS resources are tagged with `user: egru`.
