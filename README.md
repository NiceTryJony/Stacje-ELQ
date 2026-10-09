# Stacje-ELQ Bot — Render + Supabase + UptimeRobot

Архитектура: Telegram webhook → Render (Web Service, aiohttp) → Supabase (Postgres).
UptimeRobot раз в несколько минут дёргает `/health`, чтобы Render не усыплял
инстанс на free-плане. Отдельно бот сам, раз в `PING_INTERVAL_DAYS` (по
умолчанию 3) дней без активности, шлёт "бот активен" во все чаты, которые
хоть раз писали ему `/start`.

## 1. Supabase

1. Создай проект на supabase.com (бесплатный план).
2. Открой SQL Editor → вставь содержимое `schema.sql` → Run.
3. В Project Settings → API возьми:
   - `Project URL` → это `SUPABASE_URL`
   - `service_role` key (НЕ anon!) → это `SUPABASE_SERVICE_KEY`

   ⚠️ `service_role` ключ даёт полный доступ в обход RLS — никогда не
   публикуй его, храни только в переменных окружения Render.

## 2. Перенос существующих 115 станций

Запусти локально (один раз, перед первым деплоем или после):

```bash
pip install httpx
export 
export 
python import_to_supabase.py stacji-elq.json
```

Положи рядом исходный файл `stacji-elq.json` (тот, что ты присылал) —
скрипт читает его и заливает все 115 записей в таблицу `stations`.

## 3. Telegram-бот

1. Получи токен у @BotFather → это `BOT_TOKEN`.

## 4. Деплой на Render

### Вариант А — через Blueprint (render.yaml), проще

1. Залей эту папку в GitHub-репозиторий.
2. На render.com → New → Blueprint → укажи репозиторий.
3. Render подхватит `render.yaml` и попросит заполнить переменные без
   `sync: false` значений (BOT_TOKEN, BASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY).
4. `BASE_URL` узнаешь только после первого деплоя (Render выдаст домен вида
   `https://stacje-elq-bot.onrender.com`) — впиши его в переменные и
   передеплой (Manual Deploy → Deploy latest commit).

### Вариант Б — вручную

1. New → Web Service → подключи репозиторий.
2. Runtime: Python 3 (версия зафиксирована в `runtime.txt`).
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Plan: Free.
6. В Environment добавь:
   - `BOT_TOKEN`
   - `BASE_URL` — https://твой-сервис.onrender.com (после первого деплоя)
   - `WEBHOOK_SECRET` — любая случайная строка
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
   - `PING_INTERVAL_DAYS` — 3 (опционально, это значение по умолчанию)
7. Deploy. После деплоя, если `BASE_URL` ставился "вслепую" — проверь,
   что он совпадает с реальным доменом, и при расхождении обнови + передеплой.

При старте бот сам вызывает `setWebhook` на Telegram — ничего дополнительно
руками настраивать не нужно.

## 5. UptimeRobot (чтобы Render не усыплял сервис)

1. uptimerobot.com → Add New Monitor.
2. Monitor Type: HTTP(s).
3. URL: `https://твой-сервис.onrender.com/health`
4. Monitoring Interval: 5 минут (free Render засыпает примерно после
   15 минут бездействия — 5 минут с запасом).
5. Save.

Это держит сам процесс живым. Отдельно от этого бот ведёт свой учёт
активности в таблице `bot_meta` и раз в `PING_INTERVAL_DAYS` дней шлёт
сообщение "бот активен" — но это уже не про сон Render, а про то, чтобы
живой человек видел, что бот работает, если им давно не пользовались.

## Команды бота

- `/start` — регистрирует этот чат как получателя уведомлений "бот активен"
- `/add` — добавить станцию (геометка или текст `52.7086, 17.4234`,
  потом название, потом описание — или «Пропустить»)
- `/list` — список всех станций
- `/count` — количество станций в базе

## Файлы

- `bot.py` — сам бот (aiogram 3, webhook на aiohttp, /health, фоновый пинг)
- `db.py` — доступ к Supabase через REST (PostgREST)
- `schema.sql` — SQL-схема трёх таблиц: `stations`, `subscribers`, `bot_meta`
- `import_to_supabase.py` — одноразовый перенос JSON → Postgres
- `render.yaml` — Blueprint-конфиг для Render
- `runtime.txt` — фиксирует Python 3.12.7 (важно: именно из-за версии
  3.14 у тебя упала сборка pydantic-core локально — на Render такого
  не будет)
- `requirements.txt` — зависимости
