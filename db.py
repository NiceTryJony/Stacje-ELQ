"""
Слой доступа к Supabase (Postgres) через REST (PostgREST), без ORM —
достаточно httpx + сервисного ключа.
"""
import os
import re

from datetime import datetime, timezone
from typing import Any
from dotenv import load_dotenv
load_dotenv()

import httpx


_LEADING_NUMBER_RE = re.compile(r"^\s*(\d+)")


def extract_station_number(note: str | None) -> int | None:
    """Достаёт номер станции из начала note: '1419, 1420 Jaworówko 2023' -> 1419.
    None, если note пуст или не начинается с числа ('Mykola Holovchenko')."""
    if not note:
        return None
    m = _LEADING_NUMBER_RE.match(note)
    return int(m.group(1)) if m else None

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service_role key (пишет в обход RLS)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def _url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


async def add_station(
    lat: float,
    lng: float,
    name: str,
    note: str | None,
    note2: str | None = None,
    address: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "address": address,
        "lat": lat,
        "lng": lng,
        "google_maps_url": f"https://www.google.com/maps?q={lat},{lng}",
        "note": note,
        "note2": note2,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            _url("stations"),
            headers={**HEADERS, "Prefer": "return=representation"},
            json=payload,
        )
        r.raise_for_status()
        return r.json()[0]


async def get_station(station_id: int) -> dict | None:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url("stations"),
            headers=HEADERS,
            params={"select": "*", "id": f"eq.{station_id}"},
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def _escape_ilike(s: str) -> str:
    # PostgREST использует запятую и скобки как служебные символы в or=(...)
    # — экранируем их, чтобы поиск с такими символами не ломал запрос.
    return s.replace(",", "\\,").replace("(", "\\(").replace(")", "\\)")


async def find_stations(query: str, limit: int = 50) -> list[dict]:
    """Поиск по всей базе: название, описание (note) и доп. инфо (note2).
    Регистронезависимый substring-поиск (ilike) по каждому из трёх полей."""
    q = _escape_ilike(query)
    or_filter = f"name.ilike.*{q}*,note.ilike.*{q}*,note2.ilike.*{q}*"
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url("stations"),
            headers=HEADERS,
            params={
                "select": "*",
                "or": f"({or_filter})",
                "order": "id.asc",
                "limit": str(limit),
            },
        )
        r.raise_for_status()
        return r.json()


async def update_station(station_id: int, fields: dict) -> dict | None:
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            _url("stations"),
            headers={**HEADERS, "Prefer": "return=representation"},
            params={"id": f"eq.{station_id}"},
            json=fields,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


async def delete_station(station_id: int) -> bool:
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            _url("stations"),
            headers={**HEADERS, "Prefer": "return=representation"},
            params={"id": f"eq.{station_id}"},
        )
        r.raise_for_status()
        return len(r.json()) > 0


async def find_nearby(lat: float, lng: float, radius_deg: float = 0.0005) -> list[dict]:
    """Грубая проверка дублей по bounding box (~50м на этих широтах).
    Не настоящая геодезия — для предупреждения о возможном дубле этого достаточно."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url("stations"),
            headers=HEADERS,
            params={
                "select": "*",
                "and": f"(lat.gte.{lat - radius_deg},lat.lte.{lat + radius_deg},"
                       f"lng.gte.{lng - radius_deg},lng.lte.{lng + radius_deg})",
            },
        )
        r.raise_for_status()
        return r.json()


async def list_stations(limit: int = 1000) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url("stations"),
            headers=HEADERS,
            params={"select": "*", "order": "id.asc", "limit": str(limit)},
        )
        r.raise_for_status()
        return r.json()


async def count_stations() -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url("stations"),
            headers={**HEADERS, "Prefer": "count=exact"},
            params={"select": "id", "limit": "1"},
        )
        r.raise_for_status()
        content_range = r.headers.get("content-range", "*/0")
        return int(content_range.split("/")[-1])


async def import_stations_bulk(stations: list[dict]) -> int:
    """Используется только один раз, вручную, для первичного переноса JSON -> Postgres."""
    if not stations:
        return 0
    async with httpx.AsyncClient() as client:
        r = await client.post(
            _url("stations"),
            headers={**HEADERS, "Prefer": "return=minimal"},
            json=stations,
        )
        r.raise_for_status()
        return len(stations)


async def add_subscriber(chat_id: int, title: str | None) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            _url("subscribers"),
            headers={**HEADERS, "Prefer": "resolution=ignore-duplicates"},
            json={"chat_id": chat_id, "title": title},
        )
        r.raise_for_status()


async def list_subscribers() -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url("subscribers"),
            headers=HEADERS,
            params={"select": "*"},
        )
        r.raise_for_status()
        return r.json()


async def get_last_activity() -> datetime | None:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url("bot_meta"),
            headers=HEADERS,
            params={"select": "value", "key": "eq.last_activity_at"},
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return None
        return datetime.fromisoformat(rows[0]["value"])


async def set_last_activity_now() -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            _url("bot_meta"),
            headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
            json={"key": "last_activity_at", "value": now_iso},
        )
        r.raise_for_status()
