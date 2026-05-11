# expense-tracker-agentcore

AgentCore-powered version of the expense tracker. The chat agent is extracted from Flask
into a standalone [Strands Agents](https://strandsagents.com/) app deployed on
Amazon Bedrock AgentCore Runtime, with multi-turn memory and structured tools.

The original repo is at [expense-tracker](https://github.com/EricGrudzien/expense-tracker)
(tagged `v1-bedrock-flows`).

---

## Architecture

```
┌──────────┐     ┌──────────────┐     ┌─────────────────────────────┐
│ Frontend │────▶│ Flask Backend │────▶│ AgentCore Runtime           │
│ (chat.js)│     │ /api/chat    │     │  Strands Agent              │
└──────────┘     │ (proxy)      │     │  ├─ query_expenses tool     │
                 │              │     │  ├─ get_summary tool        │
                 │ /api/*       │     │  └─ chart_builder tool      │
                 │ (CRUD)       │     │                             │
                 └──────┬───────┘     │  AgentCore Memory (STM+LTM)│
                        │             └─────────────────────────────┘
                        ▼
                   expenses.db
```

**What changed from v1:**

| v1                                  | v2 (this repo)                          |
|-------------------------------------|-----------------------------------------|
| Chat logic in Flask (two-call LLM)  | Strands Agent on AgentCore Runtime      |
| Raw SQL generation by LLM           | Structured tools (no SQL injection)     |
| Single-turn chat                    | Multi-turn via AgentCore Memory         |
| Bedrock Flows for routing           | Agent handles routing internally        |
| Custom chat.log logger              | AgentCore Observability (planned)       |

---

## Project Structure

```
agent/                  Strands Agent (deployed on AgentCore Runtime)
  agent.py              Main entrypoint (@app.entrypoint)
  memory.py             AgentCore Memory setup (STM + LTM)
  requirements.txt      strands-agents, bedrock-agentcore, boto3
  tools/                Structured tools the agent can call
    query_expenses.py   Query expenses by category, date range, etc.
    get_summary.py      Aggregate totals and category breakdowns
    chart_builder.py    Generate Chart.js configs via Lambda
  prompts/
    system.txt          System prompt for the agent

backend/                Flask API (thin CRUD layer + chat proxy)
  app.py                Flask routes
  requirements.txt      flask, flask-cors, boto3
  expenses.db           SQLite database

frontend/               Vanilla JS frontend (4 pages)
lambda/chart-builder/   Deterministic chart-builder Lambda
docs/                   Reference docs from v1 planning
```

---

## Setup

### Prerequisites

- Python 3.10+
- AWS credentials configured (region: `us-east-1`)
- AgentCore Memory resource provisioned (see below)

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
# Listening on http://localhost:5000
```

### 2. Agent (local testing)

```bash
cd agent
pip install -r requirements.txt
python agent.py
# Listening on http://localhost:8080/invocations
```

Test with curl:
```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How much did I spend on hotels?"}'
```

### 3. Frontend

```bash
cd frontend
python3 -m http.server 8080
# Open http://localhost:8080
```

### 4. Provision AgentCore Memory (one-time)

```bash
cd agent
python memory.py --create
# Outputs: Memory ID: <id>
export AGENTCORE_MEMORY_ID=<id>
```

### 5. Deploy to AgentCore Runtime

```bash
pip install bedrock-agentcore-starter-toolkit
cd agent
agentcore configure --entrypoint agent.py
agentcore launch
```

---

## Implementation Phases

| Phase | Focus                        | Status      |
|-------|------------------------------|-------------|
| 1     | Foundation — agent + tools + Runtime | In progress |
| 2     | Memory + multi-turn chat UI  | Planned     |
| 3     | Code Interpreter + Observability | Planned  |
| 4     | Gateway (MCP tools) + Identity | Stretch   |

See [docs/agentcore-project-structure.md](docs/agentcore-project-structure.md) for details.
