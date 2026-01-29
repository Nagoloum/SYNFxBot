import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from accounts_config import ACCOUNTS  # Import de la config multi-comptes

load_dotenv()

st.set_page_config(page_title="Trading Journal Multi-Comptes", page_icon="📊", layout="wide")

# --- STYLE CSS ---
st.markdown("""
<style>
    .metric-card {
        background-color: #1E1E1E;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #333;
        text-align: center;
    }
    .metric-value {
        font-size: 24px;
        font-weight: bold;
        color: #00CC96;
    }
    .metric-label {
        color: #888;
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

# --- FONCTIONS ---

@st.cache_resource
def get_mongo_client():
    uri = os.getenv("MONGODB_URI")
    return MongoClient(uri, serverSelectionTimeoutMS=5000)

def get_account_db(client, account_number):
    db_name = f"trading_bot_{account_number}"
    return client[db_name]

def load_data(client, account_number, market_filter="Tous"):
    db = get_account_db(client, account_number)
    collections = db.list_collection_names()
    
    all_trades = []
    
    for col_name in collections:
        # Si on filtre par marché
        if market_filter != "Tous" and col_name != market_filter:
            continue
            
        col = db[col_name]
        trades = list(col.find().sort("open_time", -1))
        for t in trades:
            t["market"] = col_name # Ajout du nom du marché
            all_trades.append(t)
            
    if not all_trades:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_trades)
    
    # Nettoyage et Conversion
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"])
    if "close_time" in df.columns:
        df["close_time"] = pd.to_datetime(df["close_time"])
    if "profit" in df.columns:
        df["profit"] = pd.to_numeric(df["profit"]).fillna(0.0)
    
    return df

# --- SIDEBAR ---

with st.sidebar:
    st.title("📊 Trading Journal")
    
    # 1. Sélecteur de Compte
    account_options = {f"{acc.name} ({acc.account_number})": acc.account_number for acc in ACCOUNTS}
    selected_account_name = st.selectbox("👤 Choisir le Compte", list(account_options.keys()))
    selected_account_id = account_options[selected_account_name]
    
    # Connexion DB pour lister les marchés
    client = get_mongo_client()
    db = get_account_db(client, selected_account_id)
    available_markets = ["Tous"] + sorted(db.list_collection_names())
    
    # 2. Sélecteur de Marché
    selected_market = st.selectbox("📈 Marché", available_markets)
    
    st.divider()
    
    # 3. Filtre Période
    periode = st.selectbox(
        "📅 Période",
        ["Aujourd'hui", "Hier", "Cette Semaine", "Ce Mois", "Cette Année", "Tout"]
    )
    
    st.info(f"Compte ID: {selected_account_id}")

# --- REFRESH ---
st_autorefresh(interval=30000, key="data_update")

# --- MAIN ---

st.title(f"Journal de Trading : {selected_account_name}")

# Chargement des données
df_raw = load_data(client, selected_account_id, selected_market)

if df_raw.empty:
    st.warning("Aucune donnée trouvée pour ce compte/marché.")
    st.stop()

# Filtrage Temporel
df = df_raw.copy()
now = datetime.now()

if periode == "Aujourd'hui":
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    df = df[df["open_time"] >= start_date]
elif periode == "Hier":
    start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    df = df[(df["open_time"] >= start_date) & (df["open_time"] < end_date)]
elif periode == "Cette Semaine":
    start_date = now - timedelta(days=now.weekday()) # Lundi
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    df = df[df["open_time"] >= start_date]
elif periode == "Ce Mois":
    start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    df = df[df["open_time"] >= start_date]
elif periode == "Cette Année":
    start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    df = df[df["open_time"] >= start_date]

if df.empty:
    st.info(f"Aucun trade pour la période : {periode}")
    st.stop()

# --- KPI CARDS ---
col1, col2, col3, col4 = st.columns(4)

total_trades = len(df)
closed_trades = df[df["status"] == "CLOSED"]
wins = len(closed_trades[closed_trades["profit"] > 0])
losses = len(closed_trades[closed_trades["profit"] < 0])
win_rate = (wins / len(closed_trades) * 100) if len(closed_trades) > 0 else 0
total_profit = closed_trades["profit"].sum()

col1.metric("Total Trades", total_trades)
col2.metric("Win Rate", f"{win_rate:.1f}%")
col3.metric("Profit Net", f"{total_profit:.2f} $", delta_color="normal")
col4.metric("Facteur de Profit", f"{(wins/losses if losses > 0 else wins):.2f}")

# --- GRAPHIQUES ---

# 1. Courbe d'évolution du capital (Cumulatif)
if not closed_trades.empty:
    closed_trades = closed_trades.sort_values("close_time")
    closed_trades["cum_profit"] = closed_trades["profit"].cumsum()
    
    fig_equity = px.line(closed_trades, x="close_time", y="cum_profit", title="Évolution des Profits", markers=True)
    fig_equity.update_layout(xaxis_title="Date", yaxis_title="Profit Cumulé ($)")
    st.plotly_chart(fig_equity, use_container_width=True)

# 2. Répartition par Marché (Pie Chart)
if not df.empty and "market" in df.columns:
    fig_pie = px.pie(df, names="market", title="Répartition des Trades par Marché")
    st.plotly_chart(fig_pie, use_container_width=True)

# --- TABLEAU DÉTAILLÉ ---
st.subheader("Historique des Trades")

display_cols = ["ticket", "market", "type", "open_time", "open_price", "close_time", "close_price", "profit", "status"]
# Filtrer les colonnes qui existent vraiment
final_cols = [c for c in display_cols if c in df.columns]

st.dataframe(
    df[final_cols].sort_values("open_time", ascending=False),
    use_container_width=True
)
