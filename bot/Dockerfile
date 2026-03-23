FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY telegram_main.py .

CMD ["python", "-u", "telegram_main.py"]
