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
    CallbackQuery,
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
    waiting_note2 = State()


class EditStation(StatesGroup):
    waiting_field_choice = State()
    waiting_new_value = State()


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


def station_row_kb(station: dict) -> InlineKeyboardMarkup:
    """Кнопки под карточкой станции в /list и /find: карта + редактировать + удалить."""
    sid = station["id"]
    url = f"https://www.google.com/maps?q={station['lat']},{station['lng']}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗺 Карта", url=url),
                InlineKeyboardButton(text="✏️ Править", callback_data=f"edit:{sid}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delask:{sid}"),
            ]
        ]
    )


def confirm_delete_kb(station_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delyes:{station_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="delno"),
            ]
        ]
    )


def edit_field_kb(station_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Название", callback_data=f"editf:{station_id}:name")],
            [InlineKeyboardButton(text="Описание (note)", callback_data=f"editf:{station_id}:note")],
            [InlineKeyboardButton(text="Доп. инфо (note2)", callback_data=f"editf:{station_id}:note2")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="editcancel")],
        ]
    )


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
        "/list — показать станции (с кнопками карты/правки/удаления)\n"
        "/find <code>текст</code> — поиск по названию\n"
        "/count — количество станций в базе\n"
        "/cancel — отменить текущий ввод\n\n"
        "Этот чат добавлен в список получателей уведомлений \"бот активен\".",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        await message.answer("Сейчас нечего отменять.", reply_markup=ReplyKeyboardRemove())
        return
    await state.clear()
    await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())


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
        "— текстом в формате: <code>52.7086, 17.4234</code>\n\n"
        "В любой момент можно отменить через /cancel",
        parse_mode="HTML",
        reply_markup=location_request_kb(),
    )


async def _proceed_after_coords(message: Message, state: FSMContext, lat: float, lng: float):
    await state.update_data(lat=lat, lng=lng)

    nearby = await db.find_nearby(lat, lng)
    if nearby:
        names = ", ".join(s["name"] for s in nearby[:5])
        await message.answer(
            f"⚠️ Рядом уже есть станция(и): <b>{names}</b>.\n"
            f"Продолжаю добавление новой — если это дубль, потом удали лишнюю через /list.",
            parse_mode="HTML",
        )

    await state.set_state(AddStation.waiting_name)
    await message.answer("Координаты приняты ✅\nТеперь пришли название станции:", reply_markup=ReplyKeyboardRemove())


@dp.message(AddStation.waiting_coords, F.location)
async def got_location(message: Message, state: FSMContext):
    await _proceed_after_coords(message, state, message.location.latitude, message.location.longitude)


@dp.message(AddStation.waiting_coords, F.text)
async def got_coords_text(message: Message, state: FSMContext):
    m = COORD_RE.match(message.text)
    if not m:
        await message.answer(
            "Не понял формат. Пришли так: <code>52.7086, 17.4234</code> или отправь геометку кнопкой.\n"
            "(/cancel — отменить добавление)",
            parse_mode="HTML",
        )
        return
    await _proceed_after_coords(message, state, float(m.group(1)), float(m.group(2)))


@dp.message(AddStation.waiting_coords)
async def got_coords_wrong_type(message: Message):
    await message.answer("Жду координаты текстом или геометку кнопкой 👆")


@dp.message(AddStation.waiting_name, F.text)
async def got_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddStation.waiting_note)
    await message.answer(
        "Добавь описание (необязательно) или нажми «Пропустить»:",
        reply_markup=skip_kb(),
    )


@dp.message(AddStation.waiting_note, F.text)
async def got_note(message: Message, state: FSMContext):
    note = None if message.text.strip() == "Пропустить" else message.text.strip()
    await state.update_data(note=note)
    await state.set_state(AddStation.waiting_note2)
    await message.answer(
        "Доп. информация (например дата проведения работ) — необязательно, или «Пропустить»:",
        reply_markup=skip_kb(),
    )


@dp.message(AddStation.waiting_note2, F.text)
async def got_note2(message: Message, state: FSMContext):
    note2 = None if message.text.strip() == "Пропустить" else message.text.strip()
    user_data = await state.get_data()
    place = await db.add_station(
        user_data["lat"], user_data["lng"], user_data["name"], user_data.get("note"), note2
    )
    await state.clear()

    text = f"✅ Станция добавлена!\n\n<b>{place['name']}</b>\nКоординаты: <code>{place['lat']}, {place['lng']}</code>\n"
    if place.get("note"):
        text += f"Описание: {place['note']}\n"
    if place.get("note2"):
        text += f"Доп. инфо: {place['note2']}\n"

    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await message.answer("Открыть на карте:", reply_markup=place_link_kb(place["lat"], place["lng"]))


def _station_card_text(p: dict, idx: int | None = None) -> str:
    prefix = f"{idx}. " if idx is not None else ""
    text = f"{prefix}<b>{p['name']}</b>\n<code>{p['lat']}, {p['lng']}</code>"
    if p.get("note"):
        text += f"\n📝 {p['note']}"
    if p.get("note2"):
        text += f"\nℹ️ {p['note2']}"
    return text


MAX_LIST_CARDS = 30  # защита от залипания при 100+ станциях — дальше проси /find


@dp.message(Command("list"))
async def cmd_list(message: Message):
    await db.set_last_activity_now()
    stations = await db.list_stations()
    if not stations:
        await message.answer("База пуста.")
        return

    shown = stations[:MAX_LIST_CARDS]
    for idx, p in enumerate(shown, start=1):
        await message.answer(
            _station_card_text(p, idx),
            parse_mode="HTML",
            reply_markup=station_row_kb(p),
        )

    footer = f"Показано {len(shown)} из {len(stations)}."
    if len(stations) > MAX_LIST_CARDS:
        footer += " Для остальных используй /find <название>."
    await message.answer(footer)


@dp.message(Command("find"))
async def cmd_find(message: Message):
    await db.set_last_activity_now()
    query = message.text.removeprefix("/find").strip()
    if not query:
        await message.answer("Использование: <code>/find часть названия</code>", parse_mode="HTML")
        return

    results = await db.find_stations(query)
    if not results:
        await message.answer(f"По запросу «{query}» ничего не найдено.")
        return

    for p in results:
        await message.answer(_station_card_text(p), parse_mode="HTML", reply_markup=station_row_kb(p))
    await message.answer(f"Найдено: {len(results)}")


# ---------- Удаление и редактирование (через inline-кнопки) ----------

@dp.callback_query(F.data.startswith("delask:"))
async def cb_delete_ask(callback: CallbackQuery):
    station_id = int(callback.data.split(":")[1])
    station = await db.get_station(station_id)
    if not station:
        await callback.answer("Станция уже удалена.", show_alert=True)
        return
    await callback.message.answer(
        f"Удалить «<b>{station['name']}</b>»?",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(station_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delyes:"))
async def cb_delete_confirm(callback: CallbackQuery):
    station_id = int(callback.data.split(":")[1])
    ok = await db.delete_station(station_id)
    await callback.message.edit_text(
        "🗑 Станция удалена." if ok else "Не нашёл такую станцию — возможно, уже удалена.",
        reply_markup=None,
    )
    await callback.answer()


@dp.callback_query(F.data == "delno")
async def cb_delete_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Удаление отменено.", reply_markup=None)
    await callback.answer()


@dp.callback_query(F.data.startswith("edit:"))
async def cb_edit_start(callback: CallbackQuery, state: FSMContext):
    station_id = int(callback.data.split(":")[1])
    station = await db.get_station(station_id)
    if not station:
        await callback.answer("Станция не найдена.", show_alert=True)
        return
    await state.set_state(EditStation.waiting_field_choice)
    await state.update_data(station_id=station_id)
    await callback.message.answer(
        f"Что меняем у «<b>{station['name']}</b>»?",
        parse_mode="HTML",
        reply_markup=edit_field_kb(station_id),
    )
    await callback.answer()


@dp.callback_query(F.data == "editcancel")
async def cb_edit_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Редактирование отменено.", reply_markup=None)
    await callback.answer()


FIELD_LABELS = {"name": "Название", "note": "Описание", "note2": "Доп. инфо"}


@dp.callback_query(F.data.startswith("editf:"))
async def cb_edit_field_chosen(callback: CallbackQuery, state: FSMContext):
    _, station_id, field = callback.data.split(":")
    await state.update_data(station_id=int(station_id), field=field)
    await state.set_state(EditStation.waiting_new_value)
    await callback.message.edit_text(
        f"Пришли новое значение для «{FIELD_LABELS[field]}» (или /cancel):",
        reply_markup=None,
    )
    await callback.answer()


@dp.message(EditStation.waiting_new_value, F.text)
async def got_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data["field"]
    new_value = message.text.strip()
    updated = await db.update_station(data["station_id"], {field: new_value})
    await state.clear()
    if updated:
        await message.answer(
            f"✅ Обновлено: {FIELD_LABELS[field]} → {new_value}",
        )
    else:
        await message.answer("Не получилось обновить — станция могла быть удалена.")


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
    try:
        await bot.set_webhook(
            url=f"{BASE_URL}{WEBHOOK_PATH}",
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        log.info("Webhook установлен: %s%s", BASE_URL, WEBHOOK_PATH)
    except Exception:
        log.exception("НЕ УДАЛОСЬ установить webhook — бот не будет получать апдейты")
        raise
    app["ping_task"] = asyncio.create_task(keepalive_ping_loop())


async def on_shutdown(app: web.Application):
    app["ping_task"].cancel()
    # delete_webhook() умышленно не вызываем — иначе при каждом редеплое
    # Render webhook слетает и его пришлось бы ставить заново вручную.
    await bot.session.close()


async def handle_webhook(request: web.Request) -> web.Response:
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        log.warning("Webhook: неверный secret token")
        return web.Response(status=401)
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        log.exception("Ошибка при обработке webhook-апдейта")
        # Telegram не ретраит бесконечно на 200, но и не должен считать
        # сервис недоступным — поэтому отвечаем 200, ошибку видно в логах
        return web.Response(status=200)
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
