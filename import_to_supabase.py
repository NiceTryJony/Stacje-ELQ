"""
Одноразовый скрипт: читает исходный stacji-elq.json и заливает все станции
в таблицу Supabase. Запускается вручную с локальной машины, один раз.

Использование:
    export SUPABASE_URL=...
    export SUPABASE_SERVICE_KEY=...
    python import_to_supabase.py stacji-elq.json
"""
import asyncio
import json
import sys

import db


async def main(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    places = raw.get("places", [])
    rows = []
    for p in places:
        rows.append(
            {
                "name": p.get("name") or "Без названия",
                "address": p.get("address"),
                "lat": p["lat"],
                "lng": p["lng"],
                "google_maps_url": p.get("google_maps_url") or f"https://www.google.com/maps?q={p['lat']},{p['lng']}",
                "note": p.get("note"),
            }
        )

    # Supabase/PostgREST нормально ест батчи по 500-1000 строк
    batch_size = 200
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        n = await db.import_stations_bulk(batch)
        total += n
        print(f"Импортировано {total}/{len(rows)}")

    print("Готово. Всего импортировано:", total)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Использование: python import_to_supabase.py путь/к/stacji-elq.json")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
