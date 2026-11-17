import os
import time
import json
from datetime import datetime, date, timedelta
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Lichess Analytics Dashboard",
    page_icon="♟",
    layout="wide"
)

WEB_API_URL = os.getenv("WEB_API_URL", "http://127.0.0.1:8000")
LICHESS_API = "https://lichess.org/api"

STATUS_LABELS = {
    "finished": "🏁 Прошедший",
    "started": "🔥 Текущий",
    "created": "⏱ Будущий",
}

STATUS_GROUP_LABELS = {
    "finished": "Прошедшие",
    "started": "Текущие",
    "created": "Будущие",
}


# ==========================================
# Вспомогательные функции для рейтингов и дат
# ==========================================

def get_rating_bucket(rating) -> str:
    """Группирует рейтинг по категориям: < 900, 900-999, 1000-1099, 1100-1199 и т.д."""
    if rating is None or pd.isna(rating):
        return "Неизвестен"
    rating = int(rating)
    if rating < 900:
        return "< 900"
    low = (rating // 100) * 100
    return f"{low}-{low + 99}"


def bucket_sort_key(bucket: str) -> int:
    if bucket == "< 900":
        return 0
    if bucket == "Неизвестен":
        return 999999
    try:
        return int(bucket.split("-")[0])
    except Exception:
        return 999999


def build_ordered_buckets(buckets_present: list[str]) -> list[str]:
    """Создаёт непрерывную упорядоченную шкалу категорий от 900-999 (или <900) до максимума."""
    numeric_lows = [
        int(b.split("-")[0]) for b in buckets_present
        if "-" in b and b.split("-")[0].isdigit()
    ]
    ordered = []
    if "< 900" in buckets_present:
        ordered.append("< 900")
    if numeric_lows:
        min_low = min(900, min(numeric_lows))
        max_low = max(numeric_lows)
        for low in range(min_low, max_low + 1, 100):
            ordered.append(f"{low}-{low + 99}")
    if "Неизвестен" in buckets_present:
        ordered.append("Неизвестен")
    return ordered


def ts_to_local_date(ts_ms) -> date | None:
    if not ts_ms:
        return None
    return datetime.fromtimestamp(ts_ms / 1000).date()


def ts_to_str(ts_ms) -> str:
    if not ts_ms:
        return "—"
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%d.%m.%Y %H:%M")


# ==========================================
# Работа с API (с кэшированием и защитой от 429)
# ==========================================

def safe_get(url: str, headers=None, params=None, stream=False, retries: int = 3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, stream=stream, timeout=15)
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return resp
        except requests.RequestException:
            time.sleep(1)
    return None


@st.cache_data(ttl=60, show_spinner=False)
def load_tournaments_list() -> tuple[list[dict], str]:
    """Загружает список турниров с нашего веб-сервера или напрямую с Lichess API."""
    for base_url in [WEB_API_URL, "http://127.0.0.1:8000", "http://web:8000"]:
        try:
            resp = requests.get(f"{base_url}/api/tournaments?status=all", timeout=4)
            if resp.status_code == 200:
                data = resp.json().get("tournaments", [])
                if data:
                    return data, f"Локальная база ({base_url})"
        except Exception:
            continue

    # Фолбэк напрямую на Lichess API, если веб-сервер не запущен
    try:
        resp = safe_get(f"{LICHESS_API}/tournament", headers={"Accept": "application/json"})
        if resp and resp.status_code == 200:
            raw = resp.json()
            tournaments = []
            for st_name in ("started", "created", "finished"):
                for t in raw.get(st_name, []):
                    tournaments.append({
                        "id": t.get("id"),
                        "name": t.get("fullName", "Без названия"),
                        "format": t.get("perf", {}).get("name", "other").lower(),
                        "status": st_name,
                        "nb_players": t.get("nbPlayers", 0),
                        "starts_at": t.get("startsAt"),
                        "finishes_at": t.get("finishesAt"),
                        "url": f"https://lichess.org/tournament/{t.get('id')}",
                        "clock": t.get("clock", {}),
                    })
            tournaments.sort(key=lambda x: x.get("starts_at") or 0, reverse=True)
            return tournaments, "Lichess API (напрямую)"
    except Exception:
        pass

    return [], "Нет подключения"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_single_tournament_meta(tournament_id: str) -> dict | None:
    """Получает метаданные конкретного турнира по ID с Lichess API."""
    resp = safe_get(f"{LICHESS_API}/tournament/{tournament_id}", headers={"Accept": "application/json"})
    if not resp or resp.status_code != 200:
        return None
    t = resp.json()
    if t.get("isFinished"):
        status = "finished"
    elif t.get("isStarted"):
        status = "started"
    else:
        status = "created"

    starts_at = t.get("startsAt")
    # Иногда startsAt приходит строкой ISO
    if isinstance(starts_at, str):
        try:
            starts_at = int(datetime.fromisoformat(starts_at.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            starts_at = None

    finishes_at = t.get("finishesAt")
    if isinstance(finishes_at, str):
        try:
            finishes_at = int(datetime.fromisoformat(finishes_at.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            finishes_at = None
    if not finishes_at and starts_at and t.get("minutes"):
        finishes_at = starts_at + t["minutes"] * 60 * 1000

    return {
        "id": t.get("id"),
        "name": t.get("fullName", tournament_id),
        "format": t.get("perf", {}).get("name", "other").lower(),
        "status": status,
        "nb_players": t.get("nbPlayers", 0),
        "starts_at": starts_at,
        "finishes_at": finishes_at,
        "url": f"https://lichess.org/tournament/{t.get('id')}",
        "clock": t.get("clock", {}),
    }


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_tournament_players(tournament_id: str, status: str, max_players: int = 1000) -> list[dict]:
    """
    Получает список участников турнира (рейтинг, имя, ранг, очки).
    - Для started/finished использует /api/tournament/{id}/results (NDJSON)
    - Для created (будущих) или если /results пустой — постранично читает /api/tournament/{id}?page=...
    """
    players = []

    if status in ("finished", "started"):
        resp = safe_get(
            f"{LICHESS_API}/tournament/{tournament_id}/results",
            headers={"Accept": "application/x-ndjson"},
            params={"nb": max_players},
            stream=True,
        )
        if resp and resp.status_code == 200:
            for line in resp.iter_lines():
                if line:
                    try:
                        p = json.loads(line)
                        players.append({
                            "username": p.get("username") or p.get("name"),
                            "rating": p.get("rating"),
                            "rank": p.get("rank"),
                            "score": p.get("score", 0),
                            "title": p.get("title") or "",
                            "performance": p.get("performance"),
                        })
                    except json.JSONDecodeError:
                        continue
            resp.close()

    # Для будущих турниров (или если /results вернул пусто)
    if not players:
        max_pages = max(1, min(50, (max_players + 9) // 10))
        for page in range(1, max_pages + 1):
            resp = safe_get(
                f"{LICHESS_API}/tournament/{tournament_id}",
                headers={"Accept": "application/json"},
                params={"page": page},
            )
            if not resp or resp.status_code != 200:
                break
            data = resp.json()
            page_players = data.get("standing", {}).get("players", [])
            if not page_players:
                break
            for p in page_players:
                players.append({
                    "username": p.get("name") or p.get("username"),
                    "rating": p.get("rating"),
                    "rank": p.get("rank"),
                    "score": p.get("score", 0),
                    "title": p.get("title") or "",
                    "performance": p.get("performance"),
                })
            if len(page_players) < 10 or len(players) >= max_players:
                break
            time.sleep(0.1)

    for p in players:
        p["rating_bucket"] = get_rating_bucket(p.get("rating"))
    return players


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tournament_top10(tournament_id: str) -> list[dict]:
    """Быстро загружает только топ-10 финишёров прошедшего турнира."""
    players = fetch_tournament_players(tournament_id, status="finished", max_players=10)
    return [p for p in players if p.get("rank") is not None and p["rank"] <= 10][:10]


# ==========================================
# Логика расчёта таблиц и диаграмм
# ==========================================

def build_top5_registered_df(players: list[dict]) -> pd.DataFrame:
    """Задача 2: Топ-5 зарегистрировавшихся игроков (по рейтингу) в каждой категории рейтинга."""
    if not players:
        return pd.DataFrame()
    df = pd.DataFrame(players)
    df["rating_num"] = pd.to_numeric(df["rating"], errors="coerce").fillna(0)
    df["rank_num"] = pd.to_numeric(df["rank"], errors="coerce").fillna(999999)
    df = df.sort_values(by=["rating_num", "rank_num"], ascending=[False, True])

    rows = []
    buckets = sorted(df["rating_bucket"].unique(), key=bucket_sort_key)
    for bucket in buckets:
        top5 = df[df["rating_bucket"] == bucket].head(5)
        for idx, (_, row) in enumerate(top5.iterrows(), start=1):
            rows.append({
                "Категория рейтинга": bucket,
                "Топ в категории": idx,
                "Игрок": row["username"],
                "Титул": row["title"] if row["title"] else "—",
                "Рейтинг": int(row["rating"]) if pd.notna(row["rating"]) else None,
                "Очки": int(row["score"]) if pd.notna(row["score"]) else 0,
                "Место в турнире": int(row["rank"]) if pd.notna(row["rank"]) else "—",
            })
    return pd.DataFrame(rows)


def build_top5_finished_standings_df(players: list[dict]) -> pd.DataFrame:
    """Задача 3: Топ-5 по каждой категории рейтинга + место игрока в итоговой таблице турнира."""
    if not players:
        return pd.DataFrame()
    df = pd.DataFrame(players)
    df["rank_num"] = pd.to_numeric(df["rank"], errors="coerce").fillna(999999)
    df["rating_num"] = pd.to_numeric(df["rating"], errors="coerce").fillna(0)
    df = df.sort_values(by=["rank_num", "rating_num"], ascending=[True, False])

    rows = []
    buckets = sorted(df["rating_bucket"].unique(), key=bucket_sort_key)
    for bucket in buckets:
        top5 = df[df["rating_bucket"] == bucket].head(5)
        for idx, (_, row) in enumerate(top5.iterrows(), start=1):
            rows.append({
                "Категория рейтинга": bucket,
                "Топ в категории": idx,
                "Место в итоговой таблице": int(row["rank"]) if pd.notna(row["rank"]) else "—",
                "Игрок": row["username"],
                "Титул": row["title"] if row["title"] else "—",
                "Рейтинг": int(row["rating"]) if pd.notna(row["rating"]) else None,
                "Очки": int(row["score"]) if pd.notna(row["score"]) else 0,
                "Перформанс": int(row["performance"]) if pd.notna(row.get("performance")) else "—",
            })
    return pd.DataFrame(rows)


def render_rating_bar_chart(df_players: pd.DataFrame, title: str, color_col: str | None = None):
    """Задача 1: Столбчатая диаграмма количества участников по категориям рейтингов."""
    if df_players.empty:
        st.info("Нет данных об участниках для построения диаграммы.")
        return

    present = df_players["rating_bucket"].unique().tolist()
    ordered_buckets = build_ordered_buckets(present)

    if color_col:
        grouped = (
            df_players.groupby(["rating_bucket", color_col])
            .size()
            .reset_index(name="Количество участников")
        )
        # Добавляем нулевые бары для непрерывности оси X
        existing_pairs = set(zip(grouped["rating_bucket"], grouped[color_col]))
        statuses = grouped[color_col].unique().tolist()
        missing = [
            {"rating_bucket": b, color_col: s, "Количество участников": 0}
            for b in ordered_buckets for s in statuses
            if (b, s) not in existing_pairs
        ]
        if missing:
            grouped = pd.concat([grouped, pd.DataFrame(missing)], ignore_index=True)

        fig = px.bar(
            grouped,
            x="rating_bucket",
            y="Количество участников",
            color=color_col,
            barmode="group",
            title=title,
            category_orders={"rating_bucket": ordered_buckets},
            labels={"rating_bucket": "Категория рейтинга", color_col: "Категория турнира"},
            text_auto=True,
        )
    else:
        grouped = (
            df_players.groupby("rating_bucket")
            .size()
            .reset_index(name="Количество участников")
        )
        existing = set(grouped["rating_bucket"])
        missing = [
            {"rating_bucket": b, "Количество участников": 0}
            for b in ordered_buckets if b not in existing
        ]
        if missing:
            grouped = pd.concat([grouped, pd.DataFrame(missing)], ignore_index=True)

        fig = px.bar(
            grouped,
            x="rating_bucket",
            y="Количество участников",
            title=title,
            category_orders={"rating_bucket": ordered_buckets},
            labels={"rating_bucket": "Категория рейтинга"},
            text_auto=True,
            color="Количество участников",
            color_continuous_scale="Blues",
        )
        fig.update_layout(coloraxis_showscale=False)

    fig.update_layout(
        xaxis_tickangle=-35,
        height=460,
        margin=dict(l=20, r=20, t=55, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)


# ==========================================
# Основной интерфейс Streamlit
# ==========================================

st.title("♟ Аналитический дашборд турниров Lichess")

tournaments_list, data_source = load_tournaments_list()

# Обработка URL-параметров при переходе с сайта localhost:8000
qp = dict(st.query_params)
if st.session_state.get("last_qp") != qp:
    st.session_state["last_qp"] = qp
    if qp.get("tournament_id"):
        st.session_state["nav_mode"] = "🔍 Один турнир"
        st.session_state["selected_tid"] = qp["tournament_id"]
    elif qp.get("view") == "finished":
        st.session_state["nav_mode"] = "📊 Множество турниров"
        st.session_state["multi_statuses"] = ["Прошедшие"]
        if qp.get("date_from"):
            try:
                st.session_state["url_date_from"] = datetime.strptime(qp["date_from"], "%Y-%m-%d").date()
            except ValueError:
                pass
    elif qp.get("view") == "active_upcoming":
        st.session_state["nav_mode"] = "📊 Множество турниров"
        st.session_state["multi_statuses"] = ["Текущие", "Будущие"]
    elif qp.get("view") == "all":
        st.session_state["nav_mode"] = "📊 Множество турниров"
        st.session_state["multi_statuses"] = ["Прошедшие", "Текущие", "Будущие"]

if "nav_mode" not in st.session_state:
    st.session_state["nav_mode"] = "📊 Множество турниров"
if "multi_statuses" not in st.session_state:
    st.session_state["multi_statuses"] = ["Прошедшие", "Текущие", "Будущие"]

# Боковая панель навигации
with st.sidebar:
    st.header("⚙️ Навигация и фильтры")
    st.caption(f"Источник списка: {data_source}")
    st.caption(f"Всего турниров в списке: {len(tournaments_list)}")

    mode = st.radio(
        "Режим аналитики",
        ["📊 Множество турниров", "🔍 Один турнир"],
        key="nav_mode",
    )

    if st.button("🔄 Обновить список турниров"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown(
        "← [Вернуться к списку турниров (localhost:8000)](http://localhost:8000)"
    )


# ==========================================
# РЕЖИМ 1: АНАЛИЗ ОДНОГО ТУРНИРА
# ==========================================
if mode == "🔍 Один турнир":
    st.subheader("🔍 Детальная статистика одного турнира")

    tourn_map = {t["id"]: t for t in tournaments_list if t.get("id")}
    url_tid = st.session_state.get("selected_tid")
    if url_tid and url_tid not in tourn_map:
        fetched_meta = fetch_single_tournament_meta(url_tid)
        if fetched_meta:
            tourn_map[url_tid] = fetched_meta
            tournaments_list.insert(0, fetched_meta)

    if not tourn_map:
        st.warning("Не удалось загрузить список турниров.")
        st.stop()

    all_ids = list(tourn_map.keys())
    default_idx = all_ids.index(url_tid) if url_tid in all_ids else 0

    col_sel, col_lim = st.columns([3, 1])
    with col_sel:
        selected_id = st.selectbox(
            "Выберите турнир",
            options=all_ids,
            index=default_idx,
            format_func=lambda tid: (
                f"{STATUS_LABELS.get(tourn_map[tid]['status'], '')} | "
                f"{tourn_map[tid]['name']} ({tourn_map[tid]['format'].capitalize()}, "
                f"{tourn_map[tid]['nb_players']} уч.)"
            ),
        )
    with col_lim:
        max_players_single = st.number_input(
            "Макс. участников", min_value=50, max_value=3000, value=1000, step=100
        )

    t_info = tourn_map[selected_id]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Статус", STATUS_LABELS.get(t_info["status"], t_info["status"]))
    m2.metric("Формат", t_info["format"].capitalize())
    m3.metric("Участников на Lichess", t_info["nb_players"])
    m4.metric("Старт", ts_to_str(t_info.get("starts_at")))

    st.markdown(f"🔗 [Открыть турнир на Lichess.org]({t_info['url']})")

    with st.spinner("Загрузка списка участников и результатов с Lichess..."):
        players = fetch_tournament_players(selected_id, t_info["status"], max_players=int(max_players_single))

    if not players:
        st.info("В этом турнире пока нет зарегистрированных участников или API временно не вернул таблицу.")
        st.stop()

    df_players = pd.DataFrame(players)
    st.success(f"Загружено участников для анализа: **{len(df_players)}**")

    # Задача 1: Столбчатая диаграмма по категориям рейтингов
    st.markdown("### 1. Распределение участников по категориям рейтингов")
    render_rating_bar_chart(
        df_players,
        title=f"Участники турнира «{t_info['name']}» по категориям рейтингов",
    )

    st.markdown("---")

    # Задачи 2 и 3
    if t_info["status"] == "finished":
        tab_standings, tab_registered = st.tabs([
            "🏆 Топ-5 по категориям (итоговое место в турнире)",
            "⭐ Топ-5 зарегистрировавшихся по рейтингу",
        ])

        with tab_standings:
            st.markdown("### Топ-5 игроков в каждой категории рейтинга (с местом в итоговой таблице)")
            df_top5_fin = build_top5_finished_standings_df(players)
            avail_buckets = sorted(df_top5_fin["Категория рейтинга"].unique().tolist(), key=bucket_sort_key)
            chosen_buckets = st.multiselect(
                "Фильтр по категориям рейтинга:",
                options=avail_buckets,
                default=avail_buckets,
                key="fin_buckets_single",
            )
            filtered_fin = df_top5_fin[df_top5_fin["Категория рейтинга"].isin(chosen_buckets)]
            st.dataframe(filtered_fin, hide_index=True, use_container_width=True)

        with tab_registered:
            st.markdown("### Топ-5 зарегистрировавшихся игроков (по максимальному рейтингу в категории)")
            df_top5_reg = build_top5_registered_df(players)
            st.dataframe(df_top5_reg, hide_index=True, use_container_width=True)

    elif t_info["status"] == "started":
        st.markdown("### 2. Топ-5 зарегистрировавшихся игроков по категориям рейтингов (текущий турнир)")
        df_top5_reg = build_top5_registered_df(players)
        avail_buckets = sorted(df_top5_reg["Категория рейтинга"].unique().tolist(), key=bucket_sort_key)
        chosen_buckets = st.multiselect(
            "Фильтр по категориям рейтинга:",
            options=avail_buckets,
            default=avail_buckets,
            key="live_buckets_single",
        )
        st.dataframe(
            df_top5_reg[df_top5_reg["Категория рейтинга"].isin(chosen_buckets)],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.markdown("### Список зарегистрировавшихся игроков по категориям рейтингов (будущий турнир)")
        df_top5_reg = build_top5_registered_df(players)
        st.dataframe(df_top5_reg, hide_index=True, use_container_width=True)


# ==========================================
# РЕЖИМ 2: МНОЖЕСТВО ТУРНИРОВ
# ==========================================
else:
    st.subheader("📊 Сводная статистика по множеству турниров")

    if not tournaments_list:
        st.warning("Список турниров пуст. Запустите сборщик или проверьте подключение к сети.")
        st.stop()

    # Панель фильтров
    col_f1, col_f2, col_f3, col_f4 = st.columns([2, 1.5, 1.5, 1.5])

    with col_f1:
        selected_status_labels = st.multiselect(
            "Категории турниров",
            options=["Прошедшие", "Текущие", "Будущие"],
            key="multi_statuses",
        )
    label_to_status = {"Прошедшие": "finished", "Текущие": "started", "Будущие": "created"}
    selected_statuses = [label_to_status[lbl] for lbl in selected_status_labels]

    avail_formats = sorted({t["format"] for t in tournaments_list if t.get("format")})
    with col_f2:
        selected_formats = st.multiselect(
            "Форматы игр",
            options=avail_formats,
            default=avail_formats,
        )

    all_dates = [
        ts_to_local_date(t.get("finishes_at") or t.get("starts_at"))
        for t in tournaments_list
    ]
    all_dates = [d for d in all_dates if d is not None]
    min_avail_date = min(all_dates) if all_dates else date.today() - timedelta(days=7)
    max_avail_date = max(all_dates) if all_dates else date.today()
    default_from = st.session_state.get("url_date_from", min_avail_date)
    if default_from < min_avail_date:
        default_from = min_avail_date
    if default_from > max_avail_date:
        default_from = max_avail_date

    with col_f3:
        date_from = st.date_input("Прошедшие с даты", value=default_from)
    with col_f4:
        date_to = st.date_input("Прошедшие по дату", value=max(max_avail_date, date.today()))

    # Фильтруем турниры
    filtered_tournaments = []
    for t in tournaments_list:
        if t.get("status") not in selected_statuses:
            continue
        if t.get("format") not in selected_formats:
            continue
        if t.get("status") == "finished":
            t_date = ts_to_local_date(t.get("finishes_at") or t.get("starts_at"))
            if t_date and (t_date < date_from or t_date > date_to):
                continue
        filtered_tournaments.append(t)

    c_info1, c_info2 = st.columns([2, 1])
    with c_info1:
        st.info(
            f"Найдено турниров под фильтры: **{len(filtered_tournaments)}** "
            f"(Прошедших: {sum(1 for t in filtered_tournaments if t['status'] == 'finished')}, "
            f"Текущих: {sum(1 for t in filtered_tournaments if t['status'] == 'started')}, "
            f"Будущих: {sum(1 for t in filtered_tournaments if t['status'] == 'created')})"
        )
    with c_info2:
        max_tourns_to_fetch = st.slider(
            "Макс. турниров для глубокого анализа",
            min_value=1,
            max_value=max(1, min(50, len(filtered_tournaments))),
            value=min(12, max(1, len(filtered_tournaments))),
            help="Ограничение защищает от лимитов Lichess API при одновременной выгрузке сотен турниров.",
        )

    if not filtered_tournaments:
        st.warning("По выбранным фильтрам и диапазону дат турниров не найдено.")
        st.stop()

    tab1, tab2, tab3 = st.tabs([
        "📊 Столбчатая диаграмма (Задача 1)",
        "⭐ Топ-5 по каждому турниру (Задача 2)",
        "🥧 Доля Топ-10 прошедших (Задача 4)",
    ])

    # ------------------------------------------
    # ВКЛАДКА 1: Задача 1 (Столбчатая диаграмма для всех категорий турниров)
    # ------------------------------------------
    with tab1:
        st.markdown("### Распределение участников по категориям рейтингов (900-999, 1000-1099, 1100-1199...)")

        target_tourns = [t for t in filtered_tournaments if t.get("nb_players", 0) > 0][:max_tourns_to_fetch]
        if not target_tourns:
            st.info("В выбранных турнирах пока нет зарегистрированных участников.")
        else:
            all_players_rows = []
            per_tournament_players = {}

            progress_bar = st.progress(0, text="Загрузка участников турниров...")
            for idx, t in enumerate(target_tourns):
                pl = fetch_tournament_players(t["id"], t["status"], max_players=400)
                per_tournament_players[t["id"]] = pl
                st_label = STATUS_GROUP_LABELS.get(t["status"], t["status"])
                for p in pl:
                    p_copy = dict(p)
                    p_copy["tournament_id"] = t["id"]
                    p_copy["tournament_name"] = t["name"]
                    p_copy["Категория турнира"] = st_label
                    all_players_rows.append(p_copy)
                progress_bar.progress((idx + 1) / len(target_tourns), text=f"Загружено {idx + 1} из {len(target_tourns)} турниров...")
                time.sleep(0.08)
            progress_bar.empty()

            st.session_state["cached_per_tourn_players"] = per_tournament_players

            if all_players_rows:
                df_all = pd.DataFrame(all_players_rows)
                show_split = st.checkbox("Разбить столбцы по статусу турниров (Прошедшие / Текущие / Будущие)", value=True)
                render_rating_bar_chart(
                    df_all,
                    title=f"Количество участников по категориям рейтингов ({len(target_tourns)} турниров)",
                    color_col="Категория турнира" if show_split else None,
                )

                # Сводная таблица по категориям
                summary_df = (
                    df_all.groupby("rating_bucket")
                    .size()
                    .reset_index(name="Количество участников")
                )
                summary_df["sort_key"] = summary_df["rating_bucket"].apply(bucket_sort_key)
                summary_df = summary_df.sort_values("sort_key").drop(columns=["sort_key"])
                summary_df.rename(columns={"rating_bucket": "Категория рейтинга"}, inplace=True)
                with st.expander("📋 Показать сводную таблицу по категориям"):
                    st.dataframe(summary_df, hide_index=True, use_container_width=True)
            else:
                st.warning("Не удалось получить список участников.")

    # ------------------------------------------
    # ВКЛАДКА 2: Задача 2 (Топ-5 зарегистрировавшихся для КАЖДОГО текущего и прошедшего)
    # ------------------------------------------
    with tab2:
        st.markdown("### Топ-5 зарегистрировавшихся игроков по категориям рейтингов для каждого текущего и прошедшего турнира")

        cur_and_past = [
            t for t in filtered_tournaments
            if t["status"] in ("started", "finished") and t.get("nb_players", 0) > 0
        ][:max_tourns_to_fetch]

        if not cur_and_past:
            st.info("Нет текущих или прошедших турниров под выбранные фильтры.")
        else:
            cached_map = st.session_state.get("cached_per_tourn_players", {})

            missing_tourns = [t for t in cur_and_past if t["id"] not in cached_map]
            if missing_tourns:
                pb = st.progress(0, text="Загрузка данных текущих и прошедших турниров...")
                for idx, t in enumerate(missing_tourns):
                    cached_map[t["id"]] = fetch_tournament_players(t["id"], t["status"], max_players=400)
                    pb.progress((idx + 1) / len(missing_tourns))
                    time.sleep(0.08)
                pb.empty()
                st.session_state["cached_per_tourn_players"] = cached_map

            filter_cat_tab2 = st.text_input(
                "Быстрый фильтр категории рейтинга (например: 1500-1599, оставьте пустым для всех):",
                value="",
            ).strip()

            for i, t in enumerate(cur_and_past):
                players = cached_map.get(t["id"], [])
                header_txt = (
                    f"{STATUS_LABELS.get(t['status'], '')} | {t['name']} "
                    f"({t['format'].capitalize()}, {len(players)} уч., {ts_to_str(t.get('starts_at'))})"
                )
                with st.expander(header_txt, expanded=(i == 0)):
                    df_top5 = build_top5_registered_df(players)
                    if df_top5.empty:
                        st.write("Нет данных об участниках.")
                    else:
                        if filter_cat_tab2:
                            df_top5 = df_top5[df_top5["Категория рейтинга"].str.contains(filter_cat_tab2, case=False)]
                        st.dataframe(df_top5, hide_index=True, use_container_width=True)

    # ------------------------------------------
    # ВКЛАДКА 3: Задача 4 (Круговая диаграмма Топ-10 по множеству прошедших турниров)
    # ------------------------------------------
    with tab3:
        st.markdown(
            f"### Доля каждой категории рейтинга в Топ-10 прошедших турниров "
            f"(с {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')})"
        )

        finished_in_range = [
            t for t in tournaments_list
            if t.get("status") == "finished"
            and t.get("format") in selected_formats
            and t.get("nb_players", 0) > 0
            and (
                (d := ts_to_local_date(t.get("finishes_at") or t.get("starts_at"))) is not None
                and date_from <= d <= date_to
            )
        ]

        if not finished_in_range:
            st.warning(
                f"За период с {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')} "
                f"прошедших турниров в базе не найдено. "
                f"(Доступные даты в базе: с {min_avail_date.strftime('%d.%m.%Y')} по {max_avail_date.strftime('%d.%m.%Y')})"
            )
        else:
            top10_limit = min(len(finished_in_range), max(max_tourns_to_fetch, 20))
            st.write(f"Анализируется прошедших турниров: **{min(len(finished_in_range), top10_limit)}** (из {len(finished_in_range)} найденных за период)")

            top10_rows = []
            pb = st.progress(0, text="Загрузка Топ-10 финишёров прошедших турниров...")
            batch = finished_in_range[:top10_limit]
            for idx, t in enumerate(batch):
                top10 = fetch_tournament_top10(t["id"])
                for p in top10:
                    top10_rows.append({
                        "Турнир": t["name"],
                        "Формат": t["format"],
                        "Дата": ts_to_str(t.get("finishes_at") or t.get("starts_at")),
                        "Место": p["rank"],
                        "Игрок": p["username"],
                        "Рейтинг": p["rating"],
                        "Категория рейтинга": p["rating_bucket"],
                    })
                pb.progress((idx + 1) / len(batch), text=f"Обработано {idx + 1} из {len(batch)} турниров...")
                time.sleep(0.05)
            pb.empty()

            if top10_rows:
                df_top10 = pd.DataFrame(top10_rows)
                pie_df = (
                    df_top10.groupby("Категория рейтинга")
                    .size()
                    .reset_index(name="Попаданий в Топ-10")
                )
                pie_df["sort_key"] = pie_df["Категория рейтинга"].apply(bucket_sort_key)
                pie_df = pie_df.sort_values("sort_key").drop(columns=["sort_key"])
                total_entries = pie_df["Попаданий в Топ-10"].sum()
                pie_df["Доля (%)"] = (pie_df["Попаданий в Топ-10"] / total_entries * 100).round(2)

                col_chart, col_tbl = st.columns([1.4, 1])
                with col_chart:
                    fig_pie = px.pie(
                        pie_df,
                        names="Категория рейтинга",
                        values="Попаданий в Топ-10",
                        title="Доля рейтинговых категорий в Топ-10 турниров",
                        hole=0.35,
                    )
                    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
                    fig_pie.update_layout(height=480)
                    st.plotly_chart(fig_pie, use_container_width=True)

                with col_tbl:
                    st.markdown("#### Сводка по категориям")
                    st.dataframe(pie_df, hide_index=True, use_container_width=True)

                with st.expander("🏆 Список всех призёров (Топ-10 по каждому турниру)"):
                    st.dataframe(df_top10, hide_index=True, use_container_width=True)
            else:
                st.info("Не удалось получить данные Топ-10 для выбранных турниров.")