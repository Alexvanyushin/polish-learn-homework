FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Filter out macOS-specific packages that can't be installed in Linux Docker
RUN grep -v "pyobjc\|ocrmac" requirements.txt > requirements-docker.txt || true

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-docker.txt

# Copy application code
COPY . .

# Create directories if they don't exist
RUN mkdir -p material static audio

# Expose port
EXPOSE 8180

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8180"]

