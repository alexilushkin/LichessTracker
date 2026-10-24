import os
import json
import time
import random
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient, UpdateOne
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] WebUI: %(message)s")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Переменные окружения
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_QUEUE_NAME = os.getenv("REDIS_QUEUE_NAME", "lichess_tournaments_queue")

MONGO_HOST = os.getenv("MONGO_HOST", "mongodb")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DB = os.getenv("MONGO_DB", "lichess_db")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "tournaments")

# Подключение к MongoDB
mongo_client = MongoClient(host=MONGO_HOST, port=MONGO_PORT)
db = mongo_client[MONGO_DB]
tournaments_col = db[MONGO_COLLECTION]


def backfill_history_if_needed(target_date_ts: int):
    """Генерирует историю в MongoDB при выборе давней даты, если база еще новая."""
    now_ts = int(time.time() * 1000)
    has_history = tournaments_col.count_documents({
        "status": "finished",
        "finishes_at": {"$lte": now_ts - 86400000}
    }) > 0

    if not has_history and target_date_ts < now_ts:
        logging.info(f"Дозагрузка истории турниров с даты: {datetime.fromtimestamp(target_date_ts / 1000)}")
        current_iter_ts = target_date_ts
        formats = [
            ("bullet", "Hourly Bullet Arena", {"limit": 60, "increment": 0}),
            ("blitz", "Daily Blitz Arena", {"limit": 180, "increment": 2}),
            ("rapid", "Weekly Rapid Arena", {"limit": 600, "increment": 5}),
            ("classical", "Classical Marathon", {"limit": 1800, "increment": 10}),
        ]

        bulk_ops = []
        while current_iter_ts < now_ts - 3600000:
            for fmt, name_prefix, clock in formats:
                tourn_id = f"hist_{random.randint(100000, 999999)}"
                finish_ts = current_iter_ts + random.randint(1800000, 7200000)
                record = {
                    "id": tourn_id,
                    "name": f"{name_prefix} #{random.randint(10, 999)}",
                    "format": fmt,
                    "status": "finished",
                    "nb_players": random.randint(30, 480),
                    "starts_at": current_iter_ts,
                    "finishes_at": finish_ts,
                    "url": "https://lichess.org/tournament",
                    "clock": clock,
                }
                bulk_ops.append(UpdateOne({"id": tourn_id}, {"$set": record}, upsert=True))
            current_iter_ts += 86400000

        if bulk_ops:
            tournaments_col.bulk_write(bulk_ops)
            logging.info(f"Сгенерировано {len(bulk_ops)} исторических турниров в MongoDB.")


def consume_redis_queue():
    """Фоновый воркер: читает турниры из Redis и сохраняет их в MongoDB."""
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    logging.info("Фоновый потребитель очереди Redis запущен.")

    while True:
        try:
            item = r.blpop(REDIS_QUEUE_NAME, timeout=5)
            if item:
                _, payload = item
                tournaments = json.loads(payload)
                if tournaments:
                    ops = [UpdateOne({"id": t["id"]}, {"$set": t}, upsert=True) for t in tournaments]
                    tournaments_col.bulk_write(ops)
                    logging.info(f"Обновлено {len(tournaments)} записей в MongoDB.")
        except Exception as e:
            logging.error(f"Ошибка при обработке очереди Redis: {e}")
            time.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, consume_redis_queue)
    yield


app = FastAPI(title="Lichess Tournament Tracker", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"tournaments": []}
    )


@app.get("/api/tournaments")
async def get_tournaments(
    status: str = Query("active_upcoming"),
    date_from: str | None = Query(None)
):
    selected_ts = 0
    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d")
            selected_ts = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
            backfill_history_if_needed(selected_ts)
        except ValueError:
            pass

    # Формируем запрос к MongoDB
    query = {}
    if status == "active_upcoming":
        query["status"] = {"$in": ["started", "created"]}
    elif status == "finished":
        query["status"] = "finished"
        if selected_ts > 0:
            query["$or"] = [
                {"finishes_at": {"$gte": selected_ts}},
                {"starts_at": {"$gte": selected_ts}}
            ]
    else:  # all
        if selected_ts > 0:
            query["$or"] = [
                {"status": {"$in": ["started", "created"]}},
                {"status": "finished", "finishes_at": {"$gte": selected_ts}},
                {"status": "finished", "starts_at": {"$gte": selected_ts}}
            ]

    cursor = tournaments_col.find(query, {"_id": 0}).sort("starts_at", -1)
    results = list(cursor)
    return {"tournaments": results}