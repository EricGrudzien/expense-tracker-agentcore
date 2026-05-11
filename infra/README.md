# Infrastructure Deployment Guide

This directory contains everything needed to deploy and tear down the Expense Tracker
AgentCore infrastructure. All AWS resources are prefixed with `egru-` and tagged with
`user: egru`.

---

## Architecture Overview

```
CloudFormation Stack (egru-expense-agent-stack)
├── IAM Role: egru-expense-agent-runtime-role   (for AgentCore Runtime)
├── IAM Role: egru-chart-builder-lambda-role    (for Lambda)
├── ECR Repo: egru-expense-agent                (agent container image)
└── Lambda:   egru-chart-builder                (chart generation)

boto3 Scripts (no CFN support yet)
├── AgentCore Memory: egru-expense-tracker-memory
└── AgentCore Runtime: egru-expense-agent
```

---

## Prerequisites

- AWS CLI configured with credentials for account `<AWS_ACCOUNT_ID>`
- Python 3.10+ with boto3, bedrock-agentcore installed
- Docker (for building the agent container image)

```bash
pip install boto3 bedrock-agentcore
```

---

## Step-by-Step Deployment

### Step 1: Deploy the CloudFormation Stack

This creates the IAM roles, ECR repository, and chart-builder Lambda.

```bash
aws cloudformation deploy \
  --template-file infra/template.yaml \
  --stack-name egru-expense-agent-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1 \
  --tags user=egru
```

Get the outputs (you'll need these for later steps):

```bash
aws cloudformation describe-stacks \
  --stack-name egru-expense-agent-stack \
  --query "Stacks[0].Outputs" \
  --output table \
  --region us-east-1
```

Note these values:
- `ECRRepositoryUri` — e.g. `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent`
- `AgentRuntimeRoleArn` — e.g. `arn:aws:iam::<AWS_ACCOUNT_ID>:role/egru-expense-agent-runtime-role`
- `ChartBuilderFunctionName` — `egru-chart-builder`

---

### Step 2: Deploy the Chart Builder Lambda Code

The CFN stack creates the Lambda with placeholder code. Deploy the real code:

```bash
cd lambda/chart-builder
zip lambda.zip lambda_function.py
aws lambda update-function-code \
  --function-name egru-chart-builder \
  --zip-file fileb://lambda.zip \
  --region us-east-1
rm lambda.zip
cd ../..
```

---

### Step 3: Build and Push the Agent Container Image

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build the image (from project root)
docker build --platform linux/arm64 -f infra/Dockerfile -t egru-expense-agent .

# Tag and push
docker tag egru-expense-agent:latest \
  <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent:latest

docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent:latest
```

---

### Step 4: Create AgentCore Memory

```bash
cd infra
python deploy_agentcore.py --create-memory
```

This creates the memory resource and saves the ID to `.agentcore-state.json`.
Set the environment variable for the agent:

```bash
export AGENTCORE_MEMORY_ID=<id from output>
```

---

### Step 5: Create AgentCore Runtime

```bash
export ECR_IMAGE_URI=<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/egru-expense-agent:latest
export AGENT_RUNTIME_ROLE=arn:aws:iam::<AWS_ACCOUNT_ID>:role/egru-expense-agent-runtime-role

python deploy_agentcore.py --create-runtime
```

This deploys the agent container and waits for it to become ACTIVE.
The endpoint URL is saved to `.agentcore-state.json`.

---

### Step 6: Test the Deployed Agent

```bash
# Read the endpoint from state
cat infra/.agentcore-state.json

# Invoke via boto3
python -c "
import boto3, json
client = boto3.client('bedrock-agentcore', region_name='us-east-1')
resp = client.invoke_agent_runtime(
    agentRuntimeArn='<arn from state>',
    runtimeSessionId='test-session-1',
    payload=json.dumps({'prompt': 'How much did I spend on hotels?'}).encode()
)
print(json.loads(resp['body'].read()))
"
```

---

## Teardown (Complete Cleanup)

Tear down in reverse order:

```bash
# 1. Delete AgentCore resources (Runtime + Memory)
cd infra
python teardown_agentcore.py --all

# 2. Delete the ECR images (required before stack deletion)
aws ecr batch-delete-image \
  --repository-name egru-expense-agent \
  --image-ids imageTag=latest \
  --region us-east-1

# 3. Delete the CloudFormation stack
aws cloudformation delete-stack \
  --stack-name egru-expense-agent-stack \
  --region us-east-1

# 4. Wait for stack deletion
aws cloudformation wait stack-delete-complete \
  --stack-name egru-expense-agent-stack \
  --region us-east-1
```

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `template.yaml` | CloudFormation template — IAM roles, ECR repo, Lambda |
| `Dockerfile` | Agent container image definition |
| `deploy_agentcore.py` | Create AgentCore Memory + Runtime (boto3) |
| `teardown_agentcore.py` | Delete AgentCore Memory + Runtime (boto3) |
| `.agentcore-state.json` | Auto-generated — stores resource IDs (gitignored) |
| `README.md` | This file |

---

## Resource Naming Convention

All resources follow the pattern `egru-<resource-name>`:

| Resource | Name |
|----------|------|
| CloudFormation Stack | `egru-expense-agent-stack` |
| ECR Repository | `egru-expense-agent` |
| IAM Role (Runtime) | `egru-expense-agent-runtime-role` |
| IAM Role (Lambda) | `egru-chart-builder-lambda-role` |
| Lambda Function | `egru-chart-builder` |
| AgentCore Memory | `egru-expense-tracker-memory` |
| AgentCore Runtime | `egru-expense-agent` |

All resources are tagged with `user: egru`.

---

## Troubleshooting

**CloudFormation stack fails on IAM role:**
Make sure you include `--capabilities CAPABILITY_NAMED_IAM` in the deploy command.

**Docker build fails on ARM64:**
If you're on an Intel Mac, Docker Desktop handles cross-platform builds via QEMU.
Make sure "Use Rosetta for x86_64/amd64 emulation" is disabled in Docker settings.

**AgentCore Runtime stays in CREATING:**
Check CloudWatch logs. Common issues: ECR image not found, IAM role missing permissions,
container fails health check on `/ping`.

**Agent can't read expenses.db:**
In Phase 1, the DB is baked into the container image. If you update the DB locally,
rebuild and push the image. In later phases, the agent will call the backend API instead.
