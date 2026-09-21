FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine/ engine/
COPY dashboard/ dashboard/

RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && cd dashboard && npm install --omit=dev \
    && apt-get purge -y npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

EXPOSE 4173

CMD ["sh", "-c", "cd dashboard && node server.js & exec python -m engine run"]