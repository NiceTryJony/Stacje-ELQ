import asyncio
import json
import logging
import os
import re
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stacje-elq")

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "stacje_elq_data.json"

BOT_TOKEN = os.getenv("BOT_TOKEN", "8508386556:AAG7_LliJYjqMkE6RrIfZtLppWJpEOJR2yw")

COORD_RE = re.compile(
    r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)


# ---------- Хранилище ----------

def load_data() -> dict:
    if not DATA_FILE.exists():
        return {"list_name": "Stacje ELQ", "total": 0, "places": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict) -> None:
    data["total"] = len(data["places"])
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_place(lat: float, lng: float, name: str, note: str | None) -> dict:
    data = load_data()
    place = {
        "name": name,
        "address": None,
        "lat": lat,
        "lng": lng,
        "coordinates": f"{lat}, {lng}",
        "google_place_id": None,
        "google_maps_url": f"https://www.google.com/maps?q={lat},{lng}",
        "note": note,
    }
    data["places"].append(place)
    save_data(data)
    return place


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
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🗺 Открыть на карте", url=url)]]
    )


# ---------- Хэндлеры ----------

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Это бот <b>Stacje-ELQ</b>.\n\n"
        "Команды:\n"
        "/add — добавить новую станцию\n"
        "/list — показать все станции\n"
        "/count — количество станций в базе",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Command("count"))
async def cmd_count(message: Message):
    data = load_data()
    await message.answer(f"В базе сейчас: <b>{len(data['places'])}</b> станций.", parse_mode="HTML")


@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
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
    await message.answer(
        "Координаты приняты ✅\nТеперь пришли название станции:",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(AddStation.waiting_coords, F.text)
async def got_coords_text(message: Message, state: FSMContext):
    m = COORD_RE.match(message.text)
    if not m:
        await message.answer(
            "Не понял формат. Пришли так: <code>52.7086, 17.4234</code> "
            "или отправь геометку кнопкой.",
            parse_mode="HTML",
        )
        return
    lat, lng = float(m.group(1)), float(m.group(2))
    await state.update_data(lat=lat, lng=lng)
    await state.set_state(AddStation.waiting_name)
    await message.answer(
        "Координаты приняты ✅\nТеперь пришли название станции:",
        reply_markup=ReplyKeyboardRemove(),
    )


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
    user_data = await state.get_data()
    place = add_place(user_data["lat"], user_data["lng"], user_data["name"], note)
    await state.clear()

    text = (
        f"✅ Станция добавлена!\n\n"
        f"<b>{place['name']}</b>\n"
        f"Координаты: <code>{place['coordinates']}</code>\n"
    )
    if note:
        text += f"Описание: {note}\n"

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Открыть на карте:",
        reply_markup=place_link_kb(place["lat"], place["lng"]),
    )


@dp.message(Command("list"))
async def cmd_list(message: Message):
    data = load_data()
    places = data["places"]
    if not places:
        await message.answer("База пуста.")
        return

    # Телеграм режет длинные сообщения — шлём порциями по 30 штук
    chunk_size = 30
    for i in range(0, len(places), chunk_size):
        chunk = places[i : i + chunk_size]
        lines = []
        for idx, p in enumerate(chunk, start=i + 1):
            line = f"{idx}. <b>{p['name']}</b> — <code>{p['coordinates']}</code>"
            if p.get("note"):
                note_short = p["note"].splitlines()[0]
                line += f"\n    {note_short}"
            lines.append(line)
        await message.answer("\n".join(lines), parse_mode="HTML")

    await message.answer(f"Всего станций: {len(places)}")


# ---------- Импорт стартовых данных ----------

def import_initial_data(source_path: str) -> None:
    """Запускается один раз, если локальной базы ещё нет."""
    if DATA_FILE.exists():
        return
    src = Path(source_path)
    if not src.exists():
        save_data({"list_name": "Stacje ELQ", "total": 0, "places": []})
        return
    with open(src, "r", encoding="utf-8") as f:
        raw = json.load(f)
    data = {
        "list_name": raw.get("list_name", "Stacje ELQ"),
        "total": len(raw.get("places", [])),
        "places": raw.get("places", []),
    }
    save_data(data)
    log.info("Импортировано %d станций из %s", len(data["places"]), source_path)


async def main():
    import_initial_data(str(BASE_DIR / "stacji-elq-import.json"))
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
