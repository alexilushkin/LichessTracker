FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем именно docker_poller.py
COPY docker_poller.py .

# Запускаем docker_poller.py
CMD ["python", "-u", "docker_poller.py"]