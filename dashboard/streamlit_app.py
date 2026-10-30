import streamlit as st
import requests
import json

st.set_page_config(
    page_title="Lichess Analytics Dashboard",
    page_icon="♟",
    layout="wide"
)

st.title("♟ Аналитический дашборд турниров Lichess")

# ==========================================
# ВАША ЛОГИКА (Топ-5 по категориям)
# ==========================================
categories = [
    {"name": "900 - 999", "min": 900, "max": 999},
    {"name": "1000 - 1099", "min": 1000, "max": 1099},
    {"name": "1100 - 1199", "min": 1100, "max": 1199},
    {"name": "1200 - 1299", "min": 1200, "max": 1299},
    {"name": "1300 - 1399", "min": 1300, "max": 1399},
    {"name": "1400 - 1499", "min": 1400, "max": 1499},
    {"name": "1500 - 1599", "min": 1500, "max": 1599},
    {"name": "1600 - 1699", "min": 1600, "max": 1699},
    {"name": "1700 - 1799", "min": 1700, "max": 1799},
    {"name": "1800 - 1899", "min": 1800, "max": 1899},
    {"name": "1900 - 1999", "min": 1900, "max": 1999},
    {"name": "2000+", "min": 2000, "max": 9999}
]

# Кэшируем данные, чтобы не спамить Lichess API при каждом клике
@st.cache_data(ttl=300)
def get_players_from_lichess(tournament_id):
    """Fetch real players directly from Lichess for a specific tournament."""
    url = f"https://lichess.org/api/tournament/{tournament_id}/results"
    try:
        response = requests.get(url, headers={"Accept": "application/x-ndjson"}, stream=True)
        if response.status_code == 200:
            players = []
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    # Lichess returns 'rating' for finished tournaments
                    players.append({
                        "username": data.get("username", "Unknown"),
                        "rating": data.get("rating", 1500) 
                    })
            return players
        return []
    except Exception as e:
        return []

def render_top5_for_tournament(tournament_data):
    st.subheader(f"🏆 Топ-5 зарегистрировавшихся игроков")
    
    # Получаем реальных игроков из Lichess
    players_list = get_players_from_lichess(tournament_data['id'])
    
    if not players_list:
        st.info("Нет данных об игроках (возможно, турнир еще не завершен или Lichess не отдает данные).")
        return

    cols = st.columns(3)
    col_index = 0
    
    for cat in categories:
        # Фильтруем игроков по рейтингу
        players_in_cat = [
            p for p in players_list 
            if cat["min"] <= p.get("rating", 0) <= cat["max"]
        ]
        
        # Сортируем по убыванию и берем топ-5
        players_in_cat.sort(key=lambda p: p.get("rating", 0), reverse=True)
        top5 = players_in_cat[:5]
        
        # Выводим только непустые категории
        if top5:
            with cols[col_index % 3]:
                st.write(f"**Категория: {cat['name']}**")
                table_data = [
                    {"Место": i+1, "Игрок": p["username"], "Рейтинг": p["rating"]} 
                    for i, p in enumerate(top5)
                ]
                st.table(table_data)
                col_index += 1

# ==========================================
# СТРУКТУРА СТРАНИЦЫ
# ==========================================
query_params = st.query_params
tournament_id = query_params.get("tournament_id")

st.markdown("---")

# URL бэкенда (Sasha's standalone test)
API_URL = "http://127.0.0.1:8000/api/tournaments"

if tournament_id:
    # 1. Режим одного конкретного турнира (прямая ссылка)
    st.subheader(f"📊 Статистика конкретного турнира")
    st.info(f"ID турнира: **{tournament_id}**")
    
    fake_tournament = {"id": tournament_id, "name": f"Турнир {tournament_id}"}
    render_top5_for_tournament(fake_tournament)

else:
    # 2. Общий режим аналитики выборки
    st.subheader("🏆 Статистика: Прошедшие турниры")
    st.write("Выберите турнир из списка ниже, чтобы увидеть топ-5 игроков по категориям рейтинга.")

    # ВАЖНО: Запрашиваем ТОЛЬКО завершенные турниры (status="finished")
    # чтобы избежать пустых таблиц, так как Lichess отдает игроков только после финиша.
    try:
        response = requests.get(API_URL, params={"status": "finished"})
        response.raise_for_status()
        tournaments_data = response.json().get("tournaments", [])
    except Exception as e:
        st.error(f"Не удалось подключиться к бэкенду FastAPI: {e}")
        st.info("Убедитесь, что в первом терминале запущен `python web/standalone_test.py`")
        tournaments_data = []

    if not tournaments_data:
        st.warning("База данных пуста. Подождите 30-40 секунд, пока фоновый сборщик скачает турниры с Lichess, и обновите страницу.")
    else:
        # Показываем топ-5 для КАЖДОГО турнира (как требует задание)
        for t in tournaments_data:
            with st.expander(f"Турнир: {t.get('name')} (ID: {t.get('id')})"):
                render_top5_for_tournament(t)

st.markdown("---")
st.caption("Streamlit Dashboard готов к приему данных из MongoDB.")