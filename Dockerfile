# Dockerfile для деплоя на Hugging Face Spaces (Docker Space, порт 7860)
# Подходит и для любого другого Docker-хостинга (порт меняется через переменную PORT)

FROM python:3.11-slim

# PYTHONUNBUFFERED — логи сразу в консоль Space
# PORT=7860 — HF Spaces ожидает веб-сервер на этом порту (keepalive.py его слушает)
ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    TZ=Europe/Minsk

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces рекомендует непривилегированного пользователя с uid 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Сначала только requirements.txt — чтобы слой кэшировался при изменении кода
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Копируем остальной код проекта
COPY --chown=user:user . .

EXPOSE 7860

# main.py сам проверит зависимости и докачает недостающие при старте
CMD ["python", "main.py"]
