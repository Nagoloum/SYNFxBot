"""
Dashboard de Trading — EMA 20/50 Multi-Comptes
Streamlit — Refresh automatique toutes les 30s
"""
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from accounts_config import ACCOUNTS

load_dotenv()

st.set_page_config(
    page_title="Trading Journal - VOLATILITYBOT",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
<style>
    .metric-card {
        background-color: #1E1E1E;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #333;
        text-align: center;
    }
    .metric-value { font-size: 24px; font-weight: bold; color: #00CC96; }
    .metric-label { color: #888; font-size: 14px; }
    .profit-pos   { color: #00CC96; font-weight: bold; }
    .profit-neg   { color: #EF553B; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ── Connexion MongoDB ──────────────────────────────────────────

@st.cache_resource
def get_mongo_client():
    uri = os.getenv("MONGODB_URI")
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def get_account_db(client, account_number: int):
    return client[f"trading_bot_{account_number}"]


def load_data(client, account_number: int, market_filter: str = "Tous") -> pd.DataFrame:
    db          = get_account_db(client, account_number)
    collections = db.list_collection_names()
    all_trades  = []

    for col_name in collections:
        if market_filter != "Tous" and col_name != market_filter:
            continue
        trades = list(db[col_name].find().sort("open_time", -1))
        for t in trades:
            t["market"] = col_name
            all_trades.append(t)

    if not all_trades:
        return pd.DataFrame()

    df = pd.DataFrame(all_trades)

    if "open_time"  in df.columns:
        df["open_time"]  = pd.to_datetime(df["open_time"])
    if "close_time" in df.columns:
        df["close_time"] = pd.to_datetime(df["close_time"])
    if "profit"     in df.columns:
        df["profit"]     = pd.to_numeric(df["profit"], errors="coerce").fillna(0.0)

    return df


# ── Sidebar ────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 Trading Journal")
    st.caption("Stratégie : EMA 20/50 | 2% risque | R:R 1:2")

    account_options        = {f"{a.name} ({a.account_number})": a.account_number for a in ACCOUNTS}
    selected_account_name  = st.selectbox("👤 Compte", list(account_options.keys()))
    selected_account_id    = account_options[selected_account_name]

    client             = get_mongo_client()
    db                 = get_account_db(client, selected_account_id)
    available_markets  = ["Tous"] + sorted(db.list_collection_names())

    selected_market = st.selectbox("📈 Marché", available_markets)

    st.divider()

    periode = st.selectbox(
        "📅 Période",
        ["Aujourd'hui", "Hier", "Cette Semaine", "Ce Mois", "Cette Année", "Tout"]
    )

    st.info(f"Compte ID : {selected_account_id}")

# ── Refresh ────────────────────────────────────────────────────
st_autorefresh(interval=30_000, key="data_update")

# ── Titre ──────────────────────────────────────────────────────
st.title(f"Journal de Trading : {selected_account_name}")

# ── Chargement et filtrage ─────────────────────────────────────
df_raw = load_data(client, selected_account_id, selected_market)

if df_raw.empty:
    st.warning("Aucune donnée trouvée pour ce compte / marché.")
    st.stop()

df  = df_raw.copy()
now = datetime.now()

if   periode == "Aujourd'hui":
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    df    = df[df["open_time"] >= start]
elif periode == "Hier":
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=0, minute=0, second=0, microsecond=0)
    df    = df[(df["open_time"] >= start) & (df["open_time"] < end)]
elif periode == "Cette Semaine":
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    df    = df[df["open_time"] >= start]
elif periode == "Ce Mois":
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    df    = df[df["open_time"] >= start]
elif periode == "Cette Année":
    start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    df    = df[df["open_time"] >= start]

if df.empty:
    st.info(f"Aucun trade pour la période : {periode}")
    st.stop()

# ── KPIs ───────────────────────────────────────────────────────
closed = df[df["status"] == "CLOSED"].copy()    # .copy() → évite SettingWithCopyWarning
open_  = df[df["status"] == "OPEN"].copy()

wins   = (closed["profit"] > 0).sum()
losses = (closed["profit"] < 0).sum()
wr     = (wins / len(closed) * 100) if len(closed) > 0 else 0
total_profit = closed["profit"].sum()
avg_win      = closed[closed["profit"] > 0]["profit"].mean() if wins > 0  else 0
avg_loss     = closed[closed["profit"] < 0]["profit"].mean() if losses > 0 else 0
profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Trades fermés",    len(closed))
col2.metric("Positions ouvertes", len(open_))
col3.metric("Win Rate",         f"{wr:.1f}%")
col4.metric("Profit Net",       f"{total_profit:+.2f} $")
col5.metric("Profit Factor",    f"{profit_factor:.2f}")

# ── Courbe d'équité ────────────────────────────────────────────
if not closed.empty and "close_time" in closed.columns:
    closed_sorted = closed.sort_values("close_time")
    closed_sorted["cum_profit"] = closed_sorted["profit"].cumsum()

    fig_eq = px.line(
        closed_sorted, x="close_time", y="cum_profit",
        title="Évolution des Profits Cumulés",
        markers=True, color_discrete_sequence=["#00CC96"]
    )
    fig_eq.update_layout(xaxis_title="Date", yaxis_title="Profit cumulé ($)")
    st.plotly_chart(fig_eq, use_container_width=True)

# ── Distribution des profits ───────────────────────────────────
if not closed.empty:
    col_a, col_b = st.columns(2)

    with col_a:
        fig_hist = px.histogram(
            closed, x="profit", nbins=20,
            title="Distribution des P&L",
            color_discrete_sequence=["#636EFA"]
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    with col_b:
        if "market" in df.columns:
            fig_pie = px.pie(df, names="market", title="Trades par Marché")
            st.plotly_chart(fig_pie, use_container_width=True)

# ── Tableau détaillé ───────────────────────────────────────────
st.subheader("Historique des Trades")

display_cols = [
    "ticket", "market", "type", "open_time", "open_price",
    "close_time", "close_price", "profit", "status"
]
final_cols = [c for c in display_cols if c in df.columns]

st.dataframe(
    df[final_cols].sort_values("open_time", ascending=False),
    use_container_width=True
)
