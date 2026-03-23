FROM python:3.11-slim

# Install system packages: ffmpeg + OpenCV deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY processor_api.py .

# assets/campaign-logos is mounted as a volume — no COPY needed

CMD ["python", "-u", "processor_api.py"]
