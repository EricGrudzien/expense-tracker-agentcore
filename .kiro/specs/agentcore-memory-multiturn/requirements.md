# Requirements Document

## Introduction

This feature adds multi-turn conversation memory to the Expense Tracker chat agent. Currently, each chat request generates a random session ID, making every message stateless. This feature integrates AgentCore Memory (short-term and long-term) into the agent, passes persistent session IDs from the frontend through Flask to the AgentCore Runtime, and updates the chat UI to support session tracking and conversation reset.

## Glossary

- **Agent**: The Strands Agent deployed on AgentCore Runtime that answers expense-related questions using structured tools.
- **AgentCore_Runtime**: Amazon Bedrock AgentCore Runtime — the managed serverless endpoint hosting the Agent.
- **AgentCore_Memory**: Amazon Bedrock AgentCore Memory — the service providing short-term (session context) and long-term (semantic facts) memory for agents.
- **Session_Manager**: The AgentCoreMemorySessionManager that manages memory retrieval and storage for a given session.
- **Session_ID**: A unique identifier (UUID v4) representing a single conversation thread between the user and the Agent.
- **Short_Term_Memory**: Conversation context within a single session — summaries of prior turns, enabling follow-up questions.
- **Long_Term_Memory**: Semantic facts extracted across sessions — user preferences and learned information that persist beyond a single conversation.
- **Flask_Backend**: The Python Flask application that serves as a proxy between the frontend and the AgentCore Runtime.
- **Chat_Frontend**: The chat.html/chat.js frontend page that provides the conversational UI.
- **Deploy_Script**: The infra/deploy_agentcore.py script that provisions AgentCore resources.

## Requirements

### Requirement 1: Provision AgentCore Memory Resource

**User Story:** As a developer, I want to provision the AgentCore Memory resource via the deploy script, so that the agent has a memory store available for multi-turn conversations.

#### Acceptance Criteria

1. WHEN the developer runs the deploy script with the `--create-memory` flag, THE Deploy_Script SHALL create an AgentCore Memory resource with summary and semantic memory strategies
2. WHEN the memory resource is successfully created, THE Deploy_Script SHALL persist the memory ID in the `.agentcore-state.json` file
3. WHEN the memory resource is successfully created, THE Deploy_Script SHALL print the environment variable export command for `AGENTCORE_MEMORY_ID`

### Requirement 2: Integrate Memory into Agent

**User Story:** As a developer, I want the agent to use AgentCoreMemorySessionManager, so that conversation context is preserved across turns within a session.

#### Acceptance Criteria

1. WHEN the Agent receives a request with a Session_ID, THE Agent SHALL create a Session_Manager configured with that Session_ID
2. WHEN the Agent processes a message, THE Agent SHALL use the Session_Manager to retrieve prior conversation context before generating a response
3. WHEN the Agent completes a response, THE Agent SHALL use the Session_Manager to store the current turn in Short_Term_Memory
4. WHEN the Agent processes a message, THE Agent SHALL retrieve relevant Long_Term_Memory facts for the current user
5. IF the `AGENTCORE_MEMORY_ID` environment variable is not set, THEN THE Agent SHALL operate without memory and log a warning

### Requirement 3: Session ID Propagation from Frontend to Agent

**User Story:** As a user, I want my conversation context to persist across messages within the same page session, so that I can ask follow-up questions without repeating context.

#### Acceptance Criteria

1. WHEN the Chat_Frontend loads, THE Chat_Frontend SHALL generate a new Session_ID (UUID v4) and store it for the duration of the page session
2. WHEN the user sends a chat message, THE Chat_Frontend SHALL include the Session_ID in the request body
3. WHEN the Flask_Backend receives a chat request with a Session_ID, THE Flask_Backend SHALL pass the Session_ID as the `runtimeSessionId` to AgentCore_Runtime
4. WHEN the Flask_Backend receives a chat request without a Session_ID, THE Flask_Backend SHALL generate a new UUID and use it as the `runtimeSessionId`

### Requirement 4: Update Flask Chat Endpoint for Session Support

**User Story:** As a developer, I want the Flask /api/chat endpoint to accept and forward session IDs, so that the agent can maintain conversation state.

#### Acceptance Criteria

1. WHEN the Flask_Backend receives a POST to `/api/chat` with a `session_id` field in the request body, THE Flask_Backend SHALL use that value as the `runtimeSessionId` for the AgentCore_Runtime invocation
2. WHEN the Flask_Backend receives a POST to `/api/chat` without a `session_id` field, THE Flask_Backend SHALL generate a UUID v4 and use it as the `runtimeSessionId`
3. THE Flask_Backend SHALL include the `session_id` used in the response body, so the frontend can confirm which session was used

### Requirement 5: New Conversation Reset

**User Story:** As a user, I want to start a new conversation, so that I can ask unrelated questions without prior context interfering.

#### Acceptance Criteria

1. THE Chat_Frontend SHALL display a "New Conversation" button in the chat card header
2. WHEN the user clicks the "New Conversation" button, THE Chat_Frontend SHALL generate a new Session_ID
3. WHEN the user clicks the "New Conversation" button, THE Chat_Frontend SHALL clear all messages from the chat display
4. WHEN the user clicks the "New Conversation" button, THE Chat_Frontend SHALL display the welcome message again

### Requirement 6: Conversation History Display

**User Story:** As a user, I want to see my conversation history within a session, so that I can reference prior questions and answers.

#### Acceptance Criteria

1. THE Chat_Frontend SHALL render all messages exchanged within the current Session_ID in chronological order
2. WHEN the page is refreshed, THE Chat_Frontend SHALL start a new session with an empty conversation display
3. WHEN the user scrolls up in the message area, THE Chat_Frontend SHALL preserve the scroll position until the user scrolls back to the bottom or a new message arrives

### Requirement 7: Multi-Turn Context Continuity

**User Story:** As a user, I want to ask follow-up questions that reference previous answers, so that I can have natural conversations about my expenses.

#### Acceptance Criteria

1. WHEN the user asks a follow-up question referencing a prior answer (e.g., "What about airlines?" after asking about hotels), THE Agent SHALL use Short_Term_Memory to resolve the reference and provide a contextually relevant answer
2. WHEN the user asks a question within an existing session, THE Agent SHALL include relevant prior conversation context in its reasoning
3. WHEN the user starts a new session, THE Agent SHALL treat the conversation as fresh with no short-term context from the previous session

### Requirement 8: Long-Term Memory Persistence

**User Story:** As a user, I want the agent to remember facts about me across sessions, so that I do not have to repeat preferences or context each time.

#### Acceptance Criteria

1. WHEN the Agent extracts a user preference or fact during a conversation (e.g., "I mostly travel for curling competitions"), THE Agent SHALL store it in Long_Term_Memory under the semantic memory strategy
2. WHEN the user starts a new session, THE Agent SHALL retrieve relevant Long_Term_Memory facts and use them to inform responses
3. WHEN the user provides corrected information (e.g., "Actually, my main sport is hockey now"), THE Agent SHALL update the corresponding fact in Long_Term_Memory
