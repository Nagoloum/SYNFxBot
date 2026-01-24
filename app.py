import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

st.set_page_config(page_title="V100 Bot ", page_icon="📈", layout="wide")

# --- CONNEXION DB ---
@st.cache_resource(ttl=60)
def get_db_collection():
    uri = os.getenv("MONGODB_URI")
    client = MongoClient(uri)
    db = client["SYNTHBOT"]
    return db["trades_v100"]

collection = get_db_collection()

# --- CHARGEMENT DES DONNÉES ---
@st.cache_data(ttl=10)
def load_trades():
    trades = list(collection.find().sort("open_time", -1))
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    
    # Conversion forcée en datetime
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"])
    if "close_time" in df.columns:
        df["close_time"] = pd.to_datetime(df["close_time"])
    if "profit" in df.columns:
        df["profit"] = pd.to_numeric(df["profit"]).fillna(0.0)
    return df

# Rafraîchissement automatique
st_autorefresh(interval=30000, key="data_update")

df_raw = load_trades()

# --- BARRE LATÉRALE (FILTRES) ---
with st.sidebar:
    st.title("📈 Volatility 100 Index")
    st.title("⚙️ Filtres Statistiques")
    
    # 1. Filtre de Période
    periode = st.selectbox(
        "Choisir la période",
        ["Tout", "Aujourd'hui", "Cette Semaine", "Ce Mois", "Cette Année"]
    )
    
    st.divider()
    st.info(f"Dernière MAJ : {datetime.now().strftime('%H:%M:%S')}")

# --- LOGIQUE DE FILTRAGE ---
df = df_raw.copy()

if not df.empty:
    now = datetime.now()
    
    if periode == "Aujourd'hui":
        # Filtrer depuis minuit (00:00:00)
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        df = df[df["open_time"] >= start_date]
        
    elif periode == "Cette Semaine":
        # Filtrer les 7 derniers jours
        start_date = now - timedelta(days=7)
        df = df[df["open_time"] >= start_date]
        
    elif periode == "Ce Mois":
        # Filtrer depuis le 1er du mois en cours
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        df = df[df["open_time"] >= start_date]
        
    elif periode == "Cette Année":
        # Filtrer depuis le 1er Janvier
        start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        df = df[df["open_time"] >= start_date]

# --- AFFICHAGE ---
st.title(f"📈 Performance : {periode}")

if df.empty:
    st.warning(f"Aucun trade trouvé pour la période : {periode}")
    st.stop()

# --- KPI (Indicateurs) ---
col1, col2, col3, col4 = st.columns(4)
total_trades = len(df)
wins = len(df[df["profit"] > 0])
win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
net_profit = df["profit"].sum()
avg_profit = df["profit"].mean() if total_trades > 0 else 0

col1.metric("Trades", total_trades)
col2.metric("Win Rate", f"{win_rate:.1f}%")
col3.metric("Profit Net", f"{net_profit:.2f} USD")
col4.metric("Moyenne/Trade", f"{avg_profit:+.2f} USD")

# --- GRAPHIQUE ---
st.subheader("Évolution du Profit")
df_sorted = df.sort_values("open_time")
df_sorted["cum_profit"] = df_sorted["profit"].cumsum()
fig = px.area(df_sorted, x="open_time", y="cum_profit", 
              labels={"cum_profit": "Profit (USD)", "open_time": "Date"},
              color_discrete_sequence=["#00CC96"])
st.plotly_chart(fig, use_container_width=True)

# --- TABLEAU ---
st.subheader("Détails des Positions")
display_cols = ["ticket", "type", "open_price", "close_price", "profit", "status", "open_time"]
available = [c for c in display_cols if c in df.columns]

def style_profit(val):
    return f'color: {"red" if val < 0 else "green"}'

st.dataframe(
    df[available].style.applymap(style_profit, subset=['profit']),
    use_container_width=True
)