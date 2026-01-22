# app.py - Dashboard Streamlit multi-symboles avec rapport stratégie
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

st.set_page_config(page_title="Volatility Bot Dashboard", page_icon="📈", layout="wide")

@st.cache_resource(ttl=60)
def get_db_collection():
    uri = os.getenv("MONGODB_URI")
    if not uri:
        st.error("MONGODB_URI manquant")
        st.stop()

    client = MongoClient(uri)
    db = client[os.getenv("MONGODB_DB", "trading_bot")]
    return db[os.getenv("MONGODB_COLLECTION", "trades")]


collection = get_db_collection()


@st.cache_data(ttl=30)
def load_trades():
    trades = list(collection.find().sort("timestamp_open", -1))
    if not trades:
        return pd.DataFrame()

    df = pd.DataFrame(trades)
    df["timestamp_open"] = pd.to_datetime(df["timestamp_open"])
    if "timestamp_close" in df.columns:
        df["timestamp_close"] = pd.to_datetime(df["timestamp_close"])
    return df


df = load_trades()

# Sidebar
with st.sidebar:
    st.title("Volatility Bot")
    st.caption("Bot trend-following sur Volatility Indices")
    selected_symbol = st.selectbox("Marché", ["Tous"] + sorted(df['symbol'].unique()) if not df.empty else ["Tous"])

    if not df.empty:
        total_trades = len(df) if selected_symbol == "Tous" else len(df[df['symbol'] == selected_symbol])
        st.metric("Total Trades", total_trades)
        total_profit = df["profit"].sum() if selected_symbol == "Tous" else df[df['symbol'] == selected_symbol]["profit"].sum()
        st.metric("Profit Total", f"{total_profit:.2f} USD")

    st.caption(f"Mise à jour : {datetime.now().strftime('%H:%M:%S')}")
    if st.button("Rafraîchir"):
        st.rerun()

st_autorefresh(interval=300000)  # 5 min

# Titre
st.title("Dashboard Volatility Bot")

if df.empty:
    st.warning("Aucun trade")
    st.stop()

# Filtre df par symbole
if selected_symbol != "Tous":
    df = df[df['symbol'] == selected_symbol]

# Stats globales
st.header("Stats Globales")
col1, col2, col3, col4 = st.columns(4)
wins = len(df[df["result"] == "win"])
win_rate = wins / len(df) * 100 if len(df) > 0 else 0
total_profit = df["profit"].sum()
avg_profit = df["profit"].mean() if len(df) > 0 else 0

col1.metric("Trades", len(df))
col2.metric("Win Rate", f"{win_rate:.1f}%")
col3.metric("Profit Net", f"{total_profit:+.2f} USD")
col4.metric("Profit Moyen", f"{avg_profit:+.2f} USD")

# Equity curve
st.header("Évolution Capital")
df_sorted = df.sort_values("timestamp_open")
df_sorted["cum_profit"] = df_sorted["profit"].cumsum()
fig = px.line(df_sorted, x="timestamp_open", y="cum_profit", title="Profit Cumulé")
st.plotly_chart(fig, use_container_width=True)

# Derniers trades
st.header("Derniers Trades")
display_df = df[["timestamp_open", "symbol", "signal", "entry_price", "sl", "tp", "volume", "result", "profit"]].head(20)
st.dataframe(display_df, use_container_width=True)

# Performance semaine
st.header("Perf Semaine")
one_week_ago = datetime.now() - timedelta(days=7)
df_week = df[df["timestamp_open"] >= one_week_ago]
if not df_week.empty:
    week_profit = df_week["profit"].sum()
    st.metric("Profit Semaine", f"{week_profit:+.2f} USD")

# Rapport stratégie
st.header("Rapport Stratégie")
st.markdown("""
**Stratégie :** Trend-following avec filtre volatilité.
- **Marchés :** Volatility 25, 50, 75, 100.
- **Bias H4 :** EMA50 + pente pour haussier/baissier/neutre.
- **Filtre Volatilité H1 :** ATR vs avg, skip si trop calme/violent.
- **Entrée :** Pullback sur zone S/D avec rejet + RSI.
- **Gestion :** SL 1.2x ATR, TP 2x, breakeven/partial/trailing.
- **Risque :** 0.5-1% par trade, max 3 pos/symbol, stop -4% daily.
- **Stats Globales :** Voir ci-dessus.
""")