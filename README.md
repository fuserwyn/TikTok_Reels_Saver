# Social Video Fetch — отдельный проект (TikTok + Reels + YouTube Shorts)

Готовый мини-репозиторий: **библиотека** `social_video_fetch/` + **Telegram-бот** `bot/`, **Dockerfile** и **Railway**.

Никакого SoundCloud. Скопируй **всё содержимое этой папки** в корень нового Git-репозитория и деплой на Railway.

## Структура

```
.
├── Dockerfile
├── railway.json
├── requirements.txt
├── .env.example
├── bot/                   # Pyrogram (как WAV-бот: bot_token + api_id + api_hash)
│   ├── main.py
│   ├── config.py
│   ├── handlers.py
│   └── db.py              # PostgreSQL: пользователи и счётчик запросов
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
3. **Variables**: `TELEGRAM_API_KEY` или `BOT_TOKEN`; **`API_ID` и `API_HASH`** (my.telegram.org) — обязательны для Pyrogram, как в WAV-боте. Для видео >50 МБ: `TELEGRAM_SESSION` (строка Pyrogram, не Telethon).
   - Для Reels/TikTok/YouTube на IP хостинга часто нужен `cookies.txt` (формат Netscape). Два способа:
     - **Проще (без volume):** экспортируй `cookies.txt` (расширение браузера «Get cookies.txt»),
       закодируй `base64 -w0 cookies.txt` (macOS: `base64 -i cookies.txt | tr -d '\n'`) и вставь
       результат в переменную-секрет `COOKIES_TXT_B64`. Бот при старте сам запишет файл и подставит
       его в yt-dlp — больше ничего указывать не нужно.
     - **Через volume:** добавь файл в диск (например `/data/cookies.txt`) и укажи
       `YT_DLP_COOKIEFILE=/data/cookies.txt`.
     - Для YouTube экспортируй cookies именно с `youtube.com` (лучше из отдельного/второстепенного
       аккаунта — cookies дают доступ к аккаунту).
   - Можно включить автообновление `yt-dlp` в рантайме: `YT_DLP_AUTOUPDATE_HOURS=24` (раз в сутки).
   - После апдейтов Instagram пересобирай сервис, чтобы подтянуть свежий `yt-dlp`.
4. **PostgreSQL** (опционально, чтобы считать пользователей): New → Database → PostgreSQL; Railway пробросит `DATABASE_URL` в переменные сервиса с ботом. Для `/stats` укажи `STATS_ADMIN_IDS` = свой Telegram numeric ID (узнать у @userinfobot). Если при старте `CERTIFICATE_VERIFY_FAILED` — добавь переменную **`DATABASE_SSL=no-verify`**.
5. Сервис подхватит `Dockerfile` и `railway.json`.

Локально без Postgres бот работает как раньше; без `DATABASE_URL` учёт отключён.

## Использование как библиотеки (в другом коде)

```python
from social_video_fetch import download_social_video, find_tiktok_url
```

`PYTHONPATH` должен указывать на корень репозитория (в Docker уже `PYTHONPATH=/app`).

## Связь с SoundCloud Player Bot

В основном репозитории SoundCloud-бот копирует в образ только **`__init__.py` + `core/`** (см. `SoundCloudPlayerBot/Dockerfile`), без `bot/` и без своего `Dockerfile` этого проекта.
