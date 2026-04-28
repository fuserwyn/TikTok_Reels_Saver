# Social Video Fetch — отдельный проект (TikTok + Reels)

Готовый мини-репозиторий: **библиотека** `social_video_fetch/` + **Telegram-бот** `bot/`, **Dockerfile** и **Railway**.

Никакого SoundCloud. Скопируй **всё содержимое этой папки** в корень нового Git-репозитория и деплой на Railway.

## Структура

```
.
├── Dockerfile
├── railway.json
├── requirements.txt
├── .env.example
├── bot/
│   ├── main.py
│   ├── config.py
│   ├── handlers.py
│   ├── db.py              # PostgreSQL (учёт пользователей)
│   └── middleware.py
├── __init__.py             # реэкспорт API
└── core/                   # реализация пакета (yt-dlp, ссылки, cookies)
    ├── __init__.py
    ├── urls.py
    ├── download.py
    └── ...
```

## Локально

```bash
cd /path/to/repo-root
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_API_KEY=…
python -m bot.main
```

## Railway

1. New Project → Deploy from GitHub (или пустой репо + `railway up`).
2. **Root Directory** оставь пустым, если репозиторий = только эта папка; если монорепо — укажи подпапку с этим проектом.
3. **Variables**: `TELEGRAM_API_KEY` = токен бота.
4. **PostgreSQL** (опционально, чтобы считать пользователей): New → Database → PostgreSQL; Railway пробросит `DATABASE_URL` в переменные сервиса с ботом. Для `/stats` укажи `STATS_ADMIN_IDS` = свой Telegram numeric ID (узнать у @userinfobot).
5. Сервис подхватит `Dockerfile` и `railway.json`.

Локально без Postgres бот работает как раньше; без `DATABASE_URL` учёт отключён.

## Использование как библиотеки (в другом коде)

```python
from social_video_fetch import download_social_video, find_tiktok_url
```

`PYTHONPATH` должен указывать на корень репозитория (в Docker уже `PYTHONPATH=/app`).

## Связь с SoundCloud Player Bot

В основном репозитории SoundCloud-бот копирует в образ только **`__init__.py` + `core/`** (см. `SoundCloudPlayerBot/Dockerfile`), без `bot/` и без своего `Dockerfile` этого проекта.
