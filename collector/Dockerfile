FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/ ./proto/
COPY feeds.yaml .
COPY collector.py .
COPY refdata.py .
COPY compile_protos.sh .

RUN chmod +x compile_protos.sh && ./compile_protos.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "collector.py"]
