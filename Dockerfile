FROM python:3.12-slim

# System-Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies zuerst (Layer-Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Quellcode
COPY . .

# Persistente Verzeichnisse als Volume-Punkte
RUN mkdir -p data_store logs ai

# Nicht als root laufen
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Healthcheck — prüft ob bot.log in den letzten 70 Min geschrieben wurde (Bot-Zyklus = 1h)
HEALTHCHECK --interval=5m --timeout=10s --retries=3 \
    CMD python -c "import os,time; f='logs/bot.log'; \
        assert os.path.exists(f) and (time.time()-os.path.getmtime(f))<4200" || exit 1

CMD ["python", "bot.py"]
