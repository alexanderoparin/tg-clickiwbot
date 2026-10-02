FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Moscow
WORKDIR /app

# tzdata: без неё в slim-образе TZ не действует и время в логах и базе идёт по UTC
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py main.py ./
COPY core core
COPY bot bot
COPY storage storage
# assets копируются в образ, а в docker-compose ещё и монтируются с хоста:
# видео, PDF и логотип можно менять без пересборки образа
COPY assets assets

# data/ (база, выгрузки, кеш file_id) и logs/ — тома, переживают пересборку
VOLUME ["/app/data", "/app/logs"]
CMD ["python", "main.py"]
