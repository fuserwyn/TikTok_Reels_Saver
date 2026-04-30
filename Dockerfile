FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt \
 && pip install --upgrade yt-dlp

# Контекст сборки = корень этого мини-проекта (рядом с Dockerfile)
COPY __init__.py ./social_video_fetch/__init__.py
COPY core ./social_video_fetch/core
COPY bot ./bot

RUN useradd --create-home --uid 1000 bot \
 && mkdir -p /tmp/social_fetch \
 && chown -R bot:bot /app /tmp/social_fetch

USER bot

CMD ["python", "-m", "bot.main"]
