# Flask backend container with SQLite baked in (Phase 1 demo)
# Run locally: docker build -t egru-expense-backend ./backend
#              docker run -p 5000:5000 egru-expense-backend

FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY app.py .

# Copy the SQLite database (baked-in for Phase 1 demo)
COPY expenses.db .

# Flask will run via gunicorn for production-like behavior
# SQLite DB path is relative to app.py (same directory)
ENV FLASK_APP=app.py
ENV BEDROCK_REGION=us-east-1

EXPOSE 5000

# Use gunicorn with 2 workers (SQLite doesn't handle high concurrency)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
