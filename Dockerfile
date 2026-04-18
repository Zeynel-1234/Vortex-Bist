FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları (yfinance için minimal)
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

# Python paketleri
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodu
COPY . .

# Railway PORT env ile geliyor
ENV PORT=8000
EXPOSE 8000

# Health check - TEK SATIRDA BİRLEŞTİRİLDİ
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s CMD curl -f http://localhost:8000/ || exit 1

# Başlatma komutu
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
