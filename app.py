# app.py - VERSION CORRIGÉE AVEC RAFRAÎCHISSEMENT AUTOMATIQUE
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

load_dotenv()

# ===================================
# Configuration Page
# ===================================
st.set_page_config(
    page_title="XAUFxBot - Dashboard Trading XAUUSD",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===================================
# Connexion MongoDB Atlas
# ===================================
@st.cache_resource(ttl=60)  # Cache connexion 60s
def get_db_collection():
    uri = os.getenv("MONGODB_URI")
    if not uri:
        st.error("🔴 MONGODB_URI non configuré dans .env")
        st.stop()

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')  # Test connexion
        db = client[os.getenv("MONGODB_DB", "trading_bot")]
        collection = db[os.getenv("MONGODB_COLLECTION", "trades")]
        return collection
    except ConnectionFailure:
        st.error("🔴 Impossible de se connecter à MongoDB Atlas. Vérifiez votre URI.")
        st.stop()
    except Exception as e:
        st.error(f"🔴 Erreur MongoDB : {e}")
        st.stop()

trades_collection = get_db_collection()

# ===================================
# Récupération Données
# ===================================
@st.cache_data(ttl=30)  # Refresh données toutes les 30s
def load_trades():
    try:
        trades = list(trades_collection.find().sort("timestamp_open", -1))
        if not trades:
            return pd.DataFrame()
        df = pd.DataFrame(trades)
        df['timestamp_open'] = pd.to_datetime(df['timestamp_open'])
        if 'timestamp_close' in df.columns:
            df['timestamp_close'] = pd.to_datetime(df['timestamp_close'])
        return df
    except Exception as e:
        st.error(f"Erreur chargement données : {e}")
        return pd.DataFrame()

df = load_trades()

# ===================================
# Sidebar
# ===================================
with st.sidebar:
    st.image("./img/pic1.png", width=170)
    st.title("🪙 XAUFxBot")
    st.caption("Bot de trading automatisé XAUUSD")
    
    st.markdown("---")
    st.metric("Total Trades", len(df))
    if not df.empty and 'profit' in df.columns:
        total_profit = df['profit'].sum()
        st.metric("Profit Total", f"{total_profit:.2f} USD", 
                  delta=f"{total_profit:+.2f} USD")
    
    st.markdown("---")
    st.caption(f"🔄 Dernière mise à jour : {datetime.now().strftime('%H:%M:%S')}")
    
    if st.button("🔄 Rafraîchir maintenant"):
        st.rerun()

# Auto-refresh toutes les 60s
st_autorefresh(interval=60000, key="autorefresh")

# ===================================
# Titre Principal
# ===================================
st.title("📊 Dashboard Trading XAUUSD")
st.markdown(f"**Date** : {datetime.now().strftime('%d %B %Y')}")

if df.empty:
    st.warning("⚠️ Aucun trade enregistré pour le moment.")
    st.info("💡 Lancez votre bot pour commencer à voir les données ici.")
    st.stop()

# ===================================
# Stats Globales
# ===================================
st.header("📈 Statistiques Globales")

col1, col2, col3, col4 = st.columns(4)
total_trades = len(df)
wins = len(df[df['result'] == 'win']) if 'result' in df.columns else 0
win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
total_profit = df['profit'].sum() if 'profit' in df.columns else 0
avg_profit = df['profit'].mean() if 'profit' in df.columns and total_trades > 0 else 0

col1.metric("Total Trades", total_trades)
col2.metric("Taux de Succès", f"{win_rate:.1f}%", delta=f"{wins} victoires")
col3.metric("Profit Net Total", f"{total_profit:+.2f} USD")
col4.metric("Profit Moyen / Trade", f"{avg_profit:+.2f} USD")

# ===================================
# Graphique Équity Curve
# ===================================
st.header("📉 Évolution du Capital (Equity Curve)")

if 'profit' in df.columns and 'timestamp_open' in df.columns:
    df_sorted = df.sort_values('timestamp_open')
    df_sorted['cumulative_profit'] = df_sorted['profit'].cumsum()
    
    fig = px.line(
        df_sorted,
        x='timestamp_open',
        y='cumulative_profit',
        title="Évolution du Profit Cumulé",
        labels={'timestamp_open': 'Date', 'cumulative_profit': 'Profit Cumulé (USD)'},
        template="plotly_dark"
    )
    fig.update_traces(line=dict(color="#00FF00", width=3))
    fig.update_layout(showlegend=False, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Pas encore assez de données pour l'equity curve.")

# ===================================
# Tableau des Trades Récents
# ===================================
st.header("📋 Derniers Trades")

display_cols = ['timestamp_open', 'signal', 'entry_price', 'sl', 'tp', 'volume', 'result', 'profit']
if 'timestamp_close' in df.columns:
    display_cols.insert(1, 'timestamp_close')

df_display = df[display_cols].copy()
df_display = df_display.rename(columns={
    'timestamp_open': 'Ouverture',
    'timestamp_close': 'Fermeture',
    'signal': 'Signal',
    'entry_price': 'Prix Entrée',
    'sl': 'Stop Loss',
    'tp': 'Take Profit',
    'volume': 'Volume',
    'result': 'Résultat',
    'profit': 'Profit (USD)'
}).round(2)

st.dataframe(
    df_display.head(20),
    use_container_width=True,
    hide_index=True
)

# ===================================
# Stats de la Semaine
# ===================================
st.header("📅 Performance Cette Semaine")

one_week_ago = datetime.now() - timedelta(days=7)
df_week = df[df['timestamp_open'] >= one_week_ago].copy()

if not df_week.empty:
    week_trades = len(df_week)
    week_wins = len(df_week[df_week['result'] == 'win'])
    week_win_rate = (week_wins / week_trades * 100) if week_trades > 0 else 0
    week_profit = df_week['profit'].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Trades Semaine", week_trades)
    col2.metric("Win Rate Semaine", f"{week_win_rate:.1f}%")
    col3.metric("Profit Semaine", f"{week_profit:+.2f} USD")

    # Mini equity semaine
    df_week_sorted = df_week.sort_values('timestamp_open')
    df_week_sorted['cum_profit_week'] = df_week_sorted['profit'].cumsum()
    fig_week = px.area(
        df_week_sorted,
        x='timestamp_open',
        y='cum_profit_week',
        title="Profit Cumulé Cette Semaine",
        template="plotly_dark"
    )
    fig_week.update_traces(fillcolor="rgba(0,255,0,0.3)")
    st.plotly_chart(fig_week, use_container_width=True)
else:
    st.info("Aucun trade cette semaine.")

# ===================================
# Footer
# ===================================
st.markdown("---")
st.caption("XAUFxBot © 2026 - Bot de trading automatisé avec analyse technique + fondamentale")