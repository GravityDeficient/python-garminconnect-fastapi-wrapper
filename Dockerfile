FROM python:3.12-slim

WORKDIR /app

# tzdata for local time, git for installing garminconnect from master until 0.3.x lands on PyPI
RUN apt-get update && apt-get install -y tzdata git && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Create data directory for token storage
RUN mkdir -p /data/tokens

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
