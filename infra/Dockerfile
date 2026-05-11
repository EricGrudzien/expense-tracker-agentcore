# Agent container image for AgentCore Runtime
# Platform: linux/arm64 (required by AgentCore)

FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

# Install dependencies
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY agent/ .

# Copy the database (agent tools read from it directly in Phase 1)
COPY backend/expenses.db /data/expenses.db

# Set environment variables
ENV EXPENSE_DB_PATH=/data/expenses.db
ENV BEDROCK_REGION=us-east-1

# AgentCore Runtime requires port 8080
EXPOSE 8080

CMD ["python", "agent.py"]
