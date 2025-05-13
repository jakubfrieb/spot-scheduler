# syntax=docker/dockerfile:1

FROM python:3.11-slim

# Prevents Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1
# Keeps Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create a non-privileged user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY scheduleGen.py .

# Create data directory with proper permissions
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data && chmod 777 /app/data

# Create volume for persistent database storage
#VOLUME /app/data

# Switch to non-privileged user
USER appuser

# Set the entrypoint
ENTRYPOINT ["python", "scheduleGen.py"] 