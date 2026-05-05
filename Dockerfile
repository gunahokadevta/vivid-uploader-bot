FROM python:3.10-slim

# Install System Packages (FFmpeg & Aria2)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    aria2 \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files
COPY . .

# Start the bot
CMD ["python", "main.py"]
