import os
import time
import json
import logging
import requests
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Poller: %(message)s")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_QUEUE_NAME = os.getenv("REDIS_QUEUE_NAME", "lichess_tournaments_queue")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 60))

LICHESS_API_URL = "https://lichess.org/api/tournament"


def get_redis_client():
    while True:
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            r.ping()
            logging.info("Успешное подключение к Redis.")
            return r
        except Exception as e:
            logging.warning(f"Ожидание Redis ({e})... Повтор через 3 сек.")
            time.sleep(3)


def parse_and_normalize(raw_tourn: dict, status: str) -> dict:
    perf_info = raw_tourn.get("perf", {})
    return {
        "id": raw_tourn.get("id"),
        "name": raw_tourn.get("fullName", "Без названия"),
        "format": perf_info.get("name", "Other").lower(),
        "status": status,  # started, created, finished
        "nb_players": raw_tourn.get("nbPlayers", 0),
        "starts_at": raw_tourn.get("startsAt"),
        "finishes_at": raw_tourn.get("finishesAt"),
        "url": f"https://lichess.org/tournament/{raw_tourn.get('id')}",
        "clock": raw_tourn.get("clock", {}),
    }


def fetch_tournaments():
    headers = {"Accept": "application/json"}
    response = requests.get(LICHESS_API_URL, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()

    tournaments = []
    # Идущие сейчас
    for t in data.get("started", []):
        tournaments.append(parse_and_normalize(t, status="started"))
    # Предстоящие
    for t in data.get("created", []):
        tournaments.append(parse_and_normalize(t, status="created"))
    # Завершённые
    for t in data.get("finished", []):
        tournaments.append(parse_and_normalize(t, status="finished"))

    return tournaments


def main():
    r = get_redis_client()
    logging.info("Сборщик турниров Lichess успешно запущен.")

    while True:
        try:
            tournaments = fetch_tournaments()
            if tournaments:
                payload = json.dumps(tournaments)
                r.rpush(REDIS_QUEUE_NAME, payload)
                logging.info(f"Собрано {len(tournaments)} турниров (включая завершённые) -> передано в Redis.")
        except Exception as e:
            logging.error(f"Ошибка при запросе к Lichess API: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()