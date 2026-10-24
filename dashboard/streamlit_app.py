import streamlit as st

st.set_page_config(
    page_title="Lichess Analytics Dashboard",
    page_icon="♟",
    layout="wide"
)

st.title("♟ Аналитический дашборд турниров Lichess")

# Считываем переданные параметры из URL (GET-параметры)
query_params = st.query_params

view_type = query_params.get("view", "all")
tournament_id = query_params.get("tournament_id")
date_from = query_params.get("date_from")

st.markdown("---")

if tournament_id:
    # 1. Режим одного конкретного турнира
    st.subheader(f"📊 Статистика конкретного турнира")
    st.info(f"ID турнира: **{tournament_id}**")
    st.write("Ссылка на турнир в Lichess: "
             f"[Открыть на lichess.org](https://lichess.org/tournament/{tournament_id})")

    st.markdown("*(Здесь в будущем будут графики участников, распределение рейтингов, результаты партий и т.д.)*")

else:
    # 2. Общий режим аналитики выборки
    if view_type == "active_upcoming":
        st.subheader("🔥 Статистика: Текущие и предстоящие турниры")
        st.write("Режим отображения активных и планируемых соревнований.")
    elif view_type == "finished":
        st.subheader("🏆 Статистика: Прошедшие турниры")
        st.write(f"Фильтр выборки: начиная с даты **{date_from or 'Сегодня'}**")
    else:
        st.subheader("🌐 Статистика: Все турниры в базе")

    st.markdown(
        "*(Здесь в будущем будут сводные метрики, диаграммы популярности форматов bullet/blitz/rapid и активность игроков)*")

st.markdown("---")
st.caption("Streamlit Dashboard готов к приему данных из MongoDB.")