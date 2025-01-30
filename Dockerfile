# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install required system dependencies
RUN apt-get update && \
    apt-get install -y \
    curl \
    git \
    wget \
    jq \
    procps \
    python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip before installing dependencies
RUN pip install --upgrade pip

# Install Python dependencies
RUN pip install --no-cache-dir \
    pyrogram \
    tgcrypto \
    psutil \
    gunicorn==20.1.0
    
COPY requirements.txt .

# Install Python dependencies from the requirements file and gunicorn
RUN pip install --no-cache-dir -r requirements.txt \
    gunicorn==20.1.0
# Copy the application code into the container
COPY . .

# Set the default LNCrawl directory inside the container
ENV LCRAWL_PATH="/app"

# Expose the port for gunicorn web app
EXPOSE 8000

# Run both gunicorn for the web app and the Telegram bot
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:8000 & python3 main.py"]
