# expense-tracker-agentcore — Project Structure

New repo for the AgentCore-powered version of the expense tracker.
The original repo (`expense-tracker`) is tagged `v1-bedrock-flows` and left untouched.

---

## Proposed Structure

```
expense-tracker-agentcore/
│
├── README.md                    # Project overview, setup, architecture comparison vs v1
│
├── agent/                       # Strands Agents app (deployed on AgentCore Runtime)
│   ├── agent.py                 # Main agent entrypoint (@app.entrypoint)
│   ├── tools/                   # Agent tools (replace raw SQL generation)
│   │   ├── query_expenses.py    # Tool: query expenses by category, date range, etc.
│   │   ├── get_summary.py       # Tool: get totals, breakdowns
│   │   ├── chart_builder.py     # Tool: generate chart instructions
│   │   └── __init__.py
│   ├── memory.py                # AgentCore Memory setup (short-term + long-term)
│   ├── prompts/                 # System prompts for the agent
│   │   └── system.txt
│   └── requirements.txt         # strands-agents, bedrock-agentcore, bedrock-agentcore-starter-toolkit
│
├── backend/                     # Flask API (thin layer — SQLite + proxy to agent)
│   ├── app.py                   # Flask routes: expenses CRUD, /api/chat proxies to AgentCore Runtime
│   ├── requirements.txt         # flask, flask-cors, boto3
│   └── expenses.db              # SQLite database (same schema as v1)
│
├── frontend/                    # Vanilla JS frontend (carried over from v1)
│   ├── index.html               # Reports page
│   ├── app.js
│   ├── query.html               # Query page
│   ├── query.js
│   ├── categories.html          # Categories page
│   ├── categories.js
│   ├── chat.html                # Chat page (updated for multi-turn)
│   ├── chat.js                  # Updated: session management, conversation history UI
│   ├── styles.css
│   ├── query.css
│   ├── categories.css
│   └── chat.css
│
├── lambda/                      # Lambdas that survive from v1
│   └── chart-builder/           # egru-chart-builder (deterministic, no LLM)
│       └── lambda_function.py
│
├── docs/
│   ├── architecture.md          # AgentCore architecture diagram + comparison with v1
│   ├── agentcore-ideas.md       # Carried over from v1 — the ideas doc
│   └── v1-sequence.md           # Carried over — Bedrock Flow sequence diagram (for reference)
│
└── .kiro/
    └── steering/
        └── expense-tracker.md   # Updated steering doc reflecting AgentCore architecture
```

---

## What carries over from v1

| Component                | Action                                                    |
|--------------------------|-----------------------------------------------------------|
| SQLite schema + migrations | Copy `init_db()` and schema to new `backend/app.py`     |
| Frontend (all 4 pages)   | Copy as-is, then update `chat.js` for multi-turn UI      |
| Chart builder Lambda      | Copy as-is — it's deterministic, no changes needed       |
| Expense CRUD routes       | Copy from `app.py` — these don't change                  |
| Categories routes         | Copy from `app.py` — these don't change                  |
| Query routes              | Copy from `app.py` — these don't change                  |
| Steering doc              | Copy and update for new architecture                     |
| `expenses.db`             | Copy for continuity (same data)                          |

## What gets replaced

| v1 Component                     | v2 Replacement                                      |
|----------------------------------|-----------------------------------------------------|
| `chat_via_model()` (two-call)    | Strands Agent on AgentCore Runtime                  |
| `chat_via_flow()` (Bedrock Flow) | Strands Agent on AgentCore Runtime                  |
| `invoke_bedrock_flow()`          | AgentCore Runtime endpoint invocation               |
| `build_chat_system_prompt()`     | Agent system prompt in `agent/prompts/system.txt`   |
| `extract_sql()` / `validate_sql()` | Structured tools via AgentCore Gateway (or agent tools) |
| `call_bedrock()` (format answer) | Agent handles formatting natively                   |
| `chat.log` custom logger         | AgentCore Observability (OpenTelemetry)             |
| Code executor Lambda              | AgentCore Code Interpreter                          |
| Bedrock Flow (FNO4NHO5DT)        | Retired — agent handles routing internally          |
| JSON parser Lambda                | Retired — no longer needed without the Flow         |
| Single-turn chat                  | Multi-turn via AgentCore Memory                     |

## What's new

| Component                  | Purpose                                              |
|----------------------------|------------------------------------------------------|
| `agent/` directory         | Standalone Strands Agents app                        |
| AgentCore Runtime          | Managed serverless deployment of the agent           |
| AgentCore Memory           | Short-term (session) + long-term (semantic) memory   |
| AgentCore Code Interpreter | Sandboxed code execution (replaces code-executor)    |
| AgentCore Observability    | OpenTelemetry tracing, CloudWatch dashboards         |
| AgentCore Gateway          | (Phase 2) MCP tools for structured data access       |
| AgentCore Identity         | (Phase 3) User auth and scoped access                |

---

## Implementation Phases

### Phase 1: Foundation
1. Create new repo, copy over frontend + backend CRUD + chart builder
2. Build the Strands Agent with expense query tools
3. Deploy on AgentCore Runtime
4. Wire Flask `/api/chat` to proxy to the Runtime endpoint
5. Verify feature parity with v1 (text queries + chart rendering)

### Phase 2: Memory + Multi-turn
1. Set up AgentCore Memory (short-term)
2. Update `chat.js` for conversation history UI (session tracking)
3. Add long-term semantic memory strategy
4. Test follow-up questions and context continuity

### Phase 3: Code Interpreter + Observability
1. Replace code-executor Lambda with AgentCore Code Interpreter
2. Enable AgentCore Observability
3. Remove custom `chat.log` logging
4. Set up CloudWatch dashboards

### Phase 4: Gateway + Identity (stretch)
1. Define structured MCP tools via AgentCore Gateway
2. Add AgentCore Identity for user auth
3. Scope data access per user
