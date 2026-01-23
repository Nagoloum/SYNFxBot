import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.express as px
from datetime import datetime
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

st.set_page_config(page_title="V100 Bot Monitor", page_icon="📉", layout="wide")

# --- CONNEXION DB ---
@st.cache_resource(ttl=60)
def get_db_collection():
    uri = os.getenv("MONGODB_URI")
    # Configuration en dur pour correspondre à ta base SYNTHBOT
    client = MongoClient(uri)
    db = client["SYNTHBOT"]
    return db["trades_v100"]

collection = get_db_collection()

# --- CHARGEMENT ---
@st.cache_data(ttl=10)
def load_trades():
    trades = list(collection.find().sort("open_time", -1))
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    
    # Conversion dates et types
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"])
    if "close_time" in df.columns:
        df["close_time"] = pd.to_datetime(df["close_time"])
    if "profit" in df.columns:
        df["profit"] = pd.to_numeric(df["profit"]).fillna(0.0)
    return df

# Rafraîchissement automatique toutes les 30 sec
st_autorefresh(interval=30000, key="data_update")

df = load_trades()

st.title("📈 Dashboard Volatility 100")

if df.empty:
    st.warning("⚠️ Aucune donnée trouvée dans SYNTHBOT.trades_v100")
    st.stop()

# --- INDICATEURS ---
col1, col2, col3, col4 = st.columns(4)
total_trades = len(df)
wins = len(df[df["profit"] > 0])
win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
net_profit = df["profit"].sum()
open_pos = len(df[df["status"] == "OPEN"])

col1.metric("Total Trades", total_trades)
col2.metric("Win Rate", f"{win_rate:.1f}%")
col3.metric("Profit Net", f"{net_profit:.2f} USD")
col4.metric("Positions Ouvertes", open_pos)

# --- GRAPHIQUE ---
st.subheader("Performance Cumulée")
df_sorted = df.sort_values("open_time")
df_sorted["cum_profit"] = df_sorted["profit"].cumsum()
fig = px.area(df_sorted, x="open_time", y="cum_profit", 
              labels={"cum_profit": "Profit (USD)", "open_time": "Date"},
              color_discrete_sequence=["#00CC96"])
st.plotly_chart(fig, use_container_width=True)

# --- HISTORIQUE ---
st.subheader("Dernières Transactions")
# On filtre les colonnes pour un affichage propre
display_cols = ["ticket", "type", "open_price", "close_price", "profit", "status", "open_time"]
available = [c for c in display_cols if c in df.columns]

def style_profit(val):
    color = 'red' if val < 0 else 'green'
    return f'color: {color}'

st.dataframe(
    df[available].style.applymap(style_profit, subset=['profit'] if 'profit' in df.columns else []),
    use_container_width=True
)