FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt requirements.lock.txt .
RUN python -m pip install --no-cache-dir -r requirements.lock.txt
COPY repit ./repit
COPY tools ./tools
