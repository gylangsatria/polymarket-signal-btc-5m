FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir requests pandas python-dotenv polymarket-client

COPY signal.py .
COPY trader.py .

CMD ["python3", "-u", "signal.py"]


