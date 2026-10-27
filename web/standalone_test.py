import os
from pathlib import Path
import time
from datetime import datetime, timezone
import threading
import queue
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Lichess Tracker (Standalone Test)")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Очередь и база в памяти
mock_redis_queue = queue.Queue()
mock_mongo_db = {}  # {tournament_id: tournament_dict}

LICHESS_API_URL = "https://lichess.org/api/tournament"

def parse_and_normalize(raw_tourn: dict, status: str) -> dict:
    perf_info = raw_tourn.get("perf", {})
    return {
        "id": raw_tourn.get("id"),
        "name": raw_tourn.get("fullName", "Без названия"),
        "format": perf_info.get("name", "Other").lower(),
        "status": status,
        "nb_players": raw_tourn.get("nbPlayers", 0),
        "starts_at": raw_tourn.get("startsAt"),
        "finishes_at": raw_tourn.get("finishesAt"),
        "url": f"https://lichess.org/tournament/{raw_tourn.get('id')}",
        "clock": raw_tourn.get("clock", {}),
    }

def poller_worker():
    """Сборщик реальных данных с Lichess API."""
    print("[Poller] Фоновый сборщик запущен...")
    while True:
        try:
            res = requests.get(LICHESS_API_URL, headers={"Accept": "application/json"}, timeout=10)
            data = res.json()
            tournaments = []

            for t in data.get("started", []):
                tournaments.append(parse_and_normalize(t, "started"))
            for t in data.get("created", []):
                tournaments.append(parse_and_normalize(t, "created"))
            for t in data.get("finished", []):
                tournaments.append(parse_and_normalize(t, "finished"))

            if tournaments:
                mock_redis_queue.put(tournaments)
        except Exception as e:
            print(f"[Poller Error] {e}")

        time.sleep(30)

def consumer_worker():
    """Обработчик очереди: сохраняет реальные турниры в базу."""
    print("[Consumer] Обработчик очереди запущен...")
    while True:
        tournaments = mock_redis_queue.get()
        for t in tournaments:
            mock_mongo_db[t["id"]] = t
        mock_redis_queue.task_done()

# Запуск фоновых потоков
threading.Thread(target=poller_worker, daemon=True).start()
threading.Thread(target=consumer_worker, daemon=True).start()

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
        except ValueError:
            pass

    results = []
    # Выдаем только те турниры, которые РЕАЛЬНО есть в памяти
    for t in mock_mongo_db.values():
        t_status = t.get("status")
        t_finish = t.get("finishes_at") or t.get("starts_at") or 0

        if status == "active_upcoming":
            if t_status in ("started", "created"):
                results.append(t)
        elif status == "finished":
            if t_status == "finished" and (selected_ts == 0 or t_finish >= selected_ts):
                results.append(t)
        else:  # all
            if t_status == "finished":
                if selected_ts == 0 or t_finish >= selected_ts:
                    results.append(t)
            else:
                results.append(t)

    # Сортируем: сначала самые свежие (те, что начнутся/начались позже)
    results.sort(key=lambda x: x.get("starts_at") or 0, reverse=True)
    return {"tournaments": results}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)