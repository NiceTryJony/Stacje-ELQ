"""
Слой доступа к Supabase (Postgres) через REST (PostgREST), без ORM —
достаточно httpx + сервисного ключа.
"""
import os

from datetime import datetime, timezone
from typing import Any
from dotenv import load_dotenv
load_dotenv()

import httpx

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service_role key (пишет в обход RLS)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def _url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


async def add_station(lat: float, lng: float, name: str, note: str | None, address: str | None = None) -> dict:
    payload = {
        "name": name,
        "address": address,
        "lat": lat,
        "lng": lng,
        "google_maps_url": f"https://www.google.com/maps?q={lat},{lng}",
        "note": note,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            _url("stations"),
            headers={**HEADERS, "Prefer": "return=representation"},
            json=payload,
        )
        r.raise_for_status()
        return r.json()[0]


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
