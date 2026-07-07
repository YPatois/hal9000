FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends bash strace procps git && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /host-logs/description

WORKDIR /app

COPY . /app

CMD ["python", "-m", "agent.processor"]
