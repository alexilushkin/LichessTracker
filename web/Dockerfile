FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Было app:app, стало docker_app:app
CMD ["uvicorn", "docker_app:app", "--host", "0.0.0.0", "--port", "8000"]