import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    Update,
)
from aiohttp import web

import db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stacje-elq")

# ---------- Конфиг из окружения ----------

BOT_TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["BASE_URL"].rstrip("/")          # https://xxx.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "stacje-elq-secret")
PORT = int(os.environ.get("PORT", 10000))
PING_INTERVAL_DAYS = int(os.environ.get("PING_INTERVAL_DAYS", 3))

COORD_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ---------- FSM ----------

class AddStation(StatesGroup):
    waiting_coords = State()
    waiting_name = State()
    waiting_note = State()


# ---------- Клавиатуры ----------

def location_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геометку", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def skip_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def place_link_kb(lat: float, lng: float) -> InlineKeyboardMarkup:
    url = f"https://www.google.com/maps?q={lat},{lng}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗺 Открыть на карте", url=url)]])


# ---------- Хэндлеры ----------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    title = message.chat.title or message.chat.full_name or message.chat.username or str(message.chat.id)
    await db.add_subscriber(message.chat.id, title)
    await db.set_last_activity_now()
    await message.answer(
        "Привет! Это бот <b>Stacje-ELQ</b>.\n\n"
        "Команды:\n"
        "/add — добавить новую станцию\n"
        "/list — показать все станции\n"
        "/count — количество станций в базе\n\n"
        "Этот чат добавлен в список получателей уведомлений \"бот активен\".",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Command("count"))
async def cmd_count(message: Message):
    await db.set_last_activity_now()
    n = await db.count_stations()
    await message.answer(f"В базе сейчас: <b>{n}</b> станций.", parse_mode="HTML")


@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await db.set_last_activity_now()
    await state.set_state(AddStation.waiting_coords)
    await message.answer(
        "Пришли координаты станции:\n"
        "— геометкой (кнопка ниже), либо\n"
        "— текстом в формате: <code>52.7086, 17.4234</code>",
        parse_mode="HTML",
        reply_markup=location_request_kb(),
    )


@dp.message(AddStation.waiting_coords, F.location)
async def got_location(message: Message, state: FSMContext):
    lat, lng = message.location.latitude, message.location.longitude
    await state.update_data(lat=lat, lng=lng)
    await state.set_state(AddStation.waiting_name)
    await message.answer("Координаты приняты ✅\nТеперь пришли название станции:", reply_markup=ReplyKeyboardRemove())


@dp.message(AddStation.waiting_coords, F.text)
async def got_coords_text(message: Message, state: FSMContext):
    m = COORD_RE.match(message.text)
    if not m:
        await message.answer(
            "Не понял формат. Пришли так: <code>52.7086, 17.4234</code> или отправь геометку кнопкой.",
            parse_mode="HTML",
        )
        return
    lat, lng = float(m.group(1)), float(m.group(2))
    await state.update_data(lat=lat, lng=lng)
    await state.set_state(AddStation.waiting_name)
    await message.answer("Координаты приняты ✅\nТеперь пришли название станции:", reply_markup=ReplyKeyboardRemove())


@dp.message(AddStation.waiting_coords)
async def got_coords_wrong_type(message: Message):
    await message.answer("Жду координаты текстом или геометку кнопкой 👆")


@dp.message(AddStation.waiting_name, F.text)
async def got_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddStation.waiting_note)
    await message.answer("Добавь описание (необязательно) или нажми «Пропустить»:", reply_markup=skip_kb())


@dp.message(AddStation.waiting_note, F.text)
async def got_note(message: Message, state: FSMContext):
    note = None if message.text.strip() == "Пропустить" else message.text.strip()
    user_data = await state.get_data()
    place = await db.add_station(user_data["lat"], user_data["lng"], user_data["name"], note)
    await state.clear()

    text = f"✅ Станция добавлена!\n\n<b>{place['name']}</b>\nКоординаты: <code>{place['lat']}, {place['lng']}</code>\n"
    if note:
        text += f"Описание: {note}\n"

    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await message.answer("Открыть на карте:", reply_markup=place_link_kb(place["lat"], place["lng"]))


@dp.message(Command("list"))
async def cmd_list(message: Message):
    await db.set_last_activity_now()
    stations = await db.list_stations()
    if not stations:
        await message.answer("База пуста.")
        return

    chunk_size = 30
    for i in range(0, len(stations), chunk_size):
        chunk = stations[i : i + chunk_size]
        lines = []
        for idx, p in enumerate(chunk, start=i + 1):
            line = f"{idx}. <b>{p['name']}</b> — <code>{p['lat']}, {p['lng']}</code>"
            if p.get("note"):
                note_short = str(p["note"]).splitlines()[0]
                line += f"\n    {note_short}"
            lines.append(line)
        await message.answer("\n".join(lines), parse_mode="HTML")

    await message.answer(f"Всего станций: {len(stations)}")


# ---------- Фоновая задача: пинг раз в N дней ----------

async def keepalive_ping_loop():
    check_every = 60 * 60 * 6  # проверяем раз в 6 часов, не чаще
    while True:
        try:
            last = await db.get_last_activity()
            now = datetime.now(timezone.utc)
            if last is None or (now - last).days >= PING_INTERVAL_DAYS:
                subs = await db.list_subscribers()
                for sub in subs:
                    try:
                        await bot.send_message(
                            sub["chat_id"],
                            f"🟢 Бот Stacje-ELQ активен. Активности не было {PING_INTERVAL_DAYS}+ дней — проверка на связи.",
                        )
                    except Exception as e:
                        log.warning("Не смог отправить пинг в чат %s: %s", sub["chat_id"], e)
                await db.set_last_activity_now()
        except Exception as e:
            log.exception("Ошибка в keepalive_ping_loop: %s", e)
        await asyncio.sleep(check_every)


# ---------- aiohttp веб-сервер (webhook + health) ----------

async def health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def on_startup(app: web.Application):
    await bot.set_webhook(
        url=f"{BASE_URL}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    app["ping_task"] = asyncio.create_task(keepalive_ping_loop())
    log.info("Webhook установлен: %s%s", BASE_URL, WEBHOOK_PATH)


async def on_shutdown(app: web.Application):
    app["ping_task"].cancel()
    #await bot.delete_webhook()
    await bot.session.close()


async def handle_webhook(request: web.Request) -> web.Response:
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return web.Response(status=401)
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.router.add_get("/health", health)
    app.router.add_get("/", health)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
