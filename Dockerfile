FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and files
COPY . .

# Create volume mount point for persistent SQLite database
RUN mkdir -p /data

# Start the bot
CMD ["python", "-m", "bot"]
