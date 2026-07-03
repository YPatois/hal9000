FROM python:3.12-slim

RUN pip install --no-cache-dir aiohttp httpx

WORKDIR /app

COPY . /app

CMD ["python", "-m", "daemon.entry"]
