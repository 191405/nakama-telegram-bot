FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and assets
COPY . .

# Create persistent volume mount point for SQLite database and Telethon session
RUN mkdir -p /data

EXPOSE 8080

# By default, launch unified supervisor running both Web Gateway and Telegram Bot
CMD ["python", "scripts/run_all.py"]
