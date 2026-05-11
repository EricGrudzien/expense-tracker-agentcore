# Requirements Document

## Introduction

This feature covers deploying the Strands Agent to Amazon Bedrock AgentCore Runtime and wiring the Flask `/api/chat` endpoint to proxy requests to the deployed agent. This is Phase 1, steps 3–5 of the AgentCore migration: deploy the agent container, connect the backend, and verify feature parity with v1 (text queries and chart rendering).

## Glossary

- **Agent_Container**: The Docker image built from `infra/Dockerfile` containing the Strands Agent application, packaged for deployment on AgentCore Runtime (linux/arm64, port 8080).
- **AgentCore_Runtime**: Amazon Bedrock AgentCore Runtime — a managed serverless compute service that hosts agent containers and exposes them via an invocation endpoint.
- **Flask_Backend**: The Python Flask application (`backend/app.py`) serving the REST API on port 5000, including the `/api/chat` proxy endpoint.
- **Chat_Proxy**: The `/api/chat` route in the Flask_Backend that receives user messages and forwards them to the AgentCore_Runtime endpoint.
- **Runtime_Endpoint**: The HTTPS URL provided by AgentCore_Runtime after the agent is deployed and reaches ACTIVE status.
- **ECR_Repository**: The Amazon ECR repository (`egru-expense-agent`) where the Agent_Container image is stored.
- **Deploy_Script**: The boto3 script (`infra/deploy_agentcore.py`) that creates AgentCore Runtime resources and persists state to `.agentcore-state.json`.
- **State_File**: The JSON file (`infra/.agentcore-state.json`) that stores the agent runtime ARN and endpoint URL after deployment.
- **Chart_Config**: A Chart.js configuration object returned by the agent's `chart_builder` tool, rendered client-side as a canvas chart.

## Prerequisites

Before starting this feature, the CloudFormation stack must be deployed:

```bash
aws cloudformation deploy \
  --template-file infra/template.yaml \
  --stack-name egru-expense-agent-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1 \
  --tags user=egru
```

This creates the IAM role (`egru-expense-agent-runtime-role`), ECR repository (`egru-expense-agent`), and chart-builder Lambda (`egru-chart-builder`). The requirements below assume these resources already exist.

---

## Requirements

### Requirement 1: Build and Push Agent Container Image

**User Story:** As a developer, I want to build the agent container image and push it to ECR, so that AgentCore Runtime can pull and deploy it.

#### Acceptance Criteria

1. WHEN the developer runs the Docker build command from the project root, THE Agent_Container SHALL produce a linux/arm64 image tagged `egru-expense-agent:latest` that includes the agent code, dependencies, system prompt, and a copy of `expenses.db`.
2. WHEN the developer authenticates Docker to ECR and pushes the image, THE ECR_Repository SHALL contain the `latest` tag pointing to the newly built image.
3. IF the Docker build fails due to missing dependencies or incorrect platform, THEN THE Agent_Container build process SHALL produce a clear error message identifying the failing step.

### Requirement 2: Deploy Agent to AgentCore Runtime

**User Story:** As a developer, I want to deploy the agent container to AgentCore Runtime, so that the agent is accessible via a managed endpoint.

#### Acceptance Criteria

1. WHEN the developer runs `deploy_agentcore.py --create-runtime` with valid `ECR_IMAGE_URI` and `AGENT_RUNTIME_ROLE` environment variables, THE Deploy_Script SHALL create an AgentCore Runtime resource named `egru-expense-agent` with PUBLIC network mode.
2. WHEN the AgentCore_Runtime resource reaches ACTIVE status, THE Deploy_Script SHALL persist the `agent_runtime_arn` and `agent_runtime_endpoint` to the State_File.
3. WHEN the AgentCore_Runtime resource is ACTIVE, THE Runtime_Endpoint SHALL respond to invocation requests containing a JSON payload with a `prompt` field.
4. IF the `ECR_IMAGE_URI` or `AGENT_RUNTIME_ROLE` environment variable is missing, THEN THE Deploy_Script SHALL exit with a descriptive error message and non-zero exit code.
5. IF the AgentCore_Runtime resource fails to reach ACTIVE status within 10 minutes, THEN THE Deploy_Script SHALL report the failure status and exit.

### Requirement 3: Wire Flask Chat Endpoint to AgentCore Runtime

**User Story:** As a developer, I want the `/api/chat` endpoint to proxy requests to the AgentCore Runtime agent, so that the frontend chat works end-to-end through the deployed agent.

#### Acceptance Criteria

1. WHEN the Flask_Backend receives a POST to `/api/chat` with a valid `message` field, THE Chat_Proxy SHALL invoke the AgentCore_Runtime endpoint with a JSON payload containing the user message as the `prompt` field.
2. WHEN the AgentCore_Runtime returns a successful response, THE Chat_Proxy SHALL extract the `answer` field and return it in the response JSON as `{"answer": "...", "sql": null, "data": null}`.
3. WHEN the AgentCore_Runtime response contains a `chart` field with a Chart_Config object, THE Chat_Proxy SHALL include the `chart` field in the response JSON so the frontend can render it.
4. IF the AgentCore_Runtime invocation fails due to a network error or timeout, THEN THE Chat_Proxy SHALL return a 502 status with `{"error": "Agent service unavailable"}`.
5. IF the AgentCore_Runtime returns an error response, THEN THE Chat_Proxy SHALL return a 502 status with `{"error": "Agent returned an error"}`.
6. THE Chat_Proxy SHALL read the agent runtime ARN from the `AGENTCORE_RUNTIME_ARN` environment variable or fall back to reading it from the State_File.
7. THE Chat_Proxy SHALL generate a unique `runtimeSessionId` per invocation to support stateless request handling in Phase 1.

### Requirement 4: Agent Processes Natural-Language Queries

**User Story:** As a user, I want to ask natural-language questions about my expenses in the chat, so that I get accurate answers without writing SQL.

#### Acceptance Criteria

1. WHEN the agent receives a prompt asking about expense totals (e.g., "What's my total spending?"), THE AgentCore_Runtime agent SHALL use the `get_summary` tool and return a text answer containing the total amount.
2. WHEN the agent receives a prompt asking about a specific category (e.g., "Show all hotel costs"), THE AgentCore_Runtime agent SHALL use the `query_expenses` tool with the appropriate category filter and return matching results in a readable format.
3. WHEN the agent receives a prompt asking about a date range (e.g., "How much did I spend in April 2026?"), THE AgentCore_Runtime agent SHALL use the `query_expenses` tool with date filters and return the filtered total.
4. WHEN the agent receives a prompt requesting a chart (e.g., "Show me a bar chart of spending by category"), THE AgentCore_Runtime agent SHALL use the `chart_builder` tool and return a response containing a valid Chart_Config object.
5. IF the agent cannot understand the user's question, THEN THE AgentCore_Runtime agent SHALL return a helpful text response explaining what types of questions it can answer.

### Requirement 5: End-to-End Feature Parity with v1

**User Story:** As a user, I want the chat experience to work the same as v1, so that text queries and chart rendering continue to function after the AgentCore migration.

#### Acceptance Criteria

1. WHEN a user sends a text query through the frontend chat, THE system (Frontend → Flask_Backend → AgentCore_Runtime → Agent) SHALL return a text answer displayed in an assistant chat bubble.
2. WHEN a user requests a chart through the frontend chat, THE system SHALL return a Chart_Config that the frontend renders as a Chart.js canvas inside the assistant chat bubble.
3. THE Chat_Proxy response format SHALL maintain backward compatibility with the existing frontend contract: `{"answer": string, "sql": string|null, "data": any|null, "chart": object|null}`.
4. WHILE the AgentCore_Runtime agent is processing a request, THE Flask_Backend SHALL not timeout before the agent completes (timeout set to at least 60 seconds for the upstream call).
5. IF the agent is not deployed or unreachable, THEN THE Chat_Proxy SHALL return a user-friendly error message rather than an unhandled exception.

### Requirement 6: Configuration and Environment Management

**User Story:** As a developer, I want clear configuration for connecting the Flask backend to the deployed agent, so that I can easily switch between local development and the deployed runtime.

#### Acceptance Criteria

1. THE Flask_Backend SHALL support an `AGENTCORE_RUNTIME_ARN` environment variable that specifies the deployed agent's ARN for invocation.
2. WHERE the `AGENTCORE_RUNTIME_ARN` environment variable is not set, THE Flask_Backend SHALL attempt to read the ARN from the State_File at `infra/.agentcore-state.json`.
3. IF neither the environment variable nor the State_File provides a valid ARN, THEN THE Flask_Backend SHALL log a warning at startup and return a 503 response from the Chat_Proxy with `{"error": "Agent runtime not configured"}`.
4. THE Flask_Backend SHALL use the `BEDROCK_REGION` environment variable (defaulting to `us-east-1`) for the boto3 client that invokes the AgentCore_Runtime.
