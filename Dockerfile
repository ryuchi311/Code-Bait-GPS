# Use the official lightweight Python image.
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Install system dependencies for common Python packages (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . /app

# Expose port Cloud Run expects (8080)
EXPOSE 8080

# Prefer 0.0.0.0 binding so container accepts external connections
# Use gunicorn with 2 workers for modest concurrency. Set timeout to 0 to disable
# worker timeout in case of long-running requests (adjust per needs).
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "2", "--timeout", "0", "app:app"]
