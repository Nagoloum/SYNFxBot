import time
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
import numpy as np
import logging
from datetime import datetime

from database import save_open, collection
from utils import send_telegram_alert
from config import SYMBOL, MAGIC_NUMBER, START_HOUR, END_HOUR

# ─── PARAMÈTRES TECHNIQUES ────────────────────────────────────────────────
MIN_LOT_V100     = 1.0
EMA_PERIOD_H4    = 50
MAX_ALLOWED_SPREAD = 0.60


def get_price_data(symbol, timeframe, n_bars=300):
    """Récupère les données OHLCV"""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


def get_zigzag(df, depth=10, zz_column_name='zz'):
    zz_result = ta.zigzag(high=df['high'], low=df['low'], depth=depth)
    
    if isinstance(zz_result, pd.Series):
        df[zz_column_name] = zz_result
    elif isinstance(zz_result, pd.DataFrame):
        # Prendre la colonne qui contient le plus de valeurs non-null
        best_col = zz_result.notna().sum().idxmax()
        df[zz_column_name] = zz_result[best_col]
        # logging.info(f"Colonne zigzag sélectionnée automatiquement : {best_col}")
    else:
        raise ValueError("ta.zigzag a retourné un type inattendu")
    
    return df.dropna(subset=[zz_column_name])

def detect_advanced_patterns(df):
    """Détection simple W / M via ZigZag"""
    peaks = get_zigzag(df)
    if len(peaks) < 5:
        return None

    p = peaks['zz'].values
    # Double Bottom (W)
    if p[-1] > p[-2] and abs(p[-2] - p[-4]) < (p[-1] * 0.002) and p[-3] > p[-2]:
        return "DOUBLE_BOTTOM_W"
    # Double Top (M)
    if p[-1] < p[-2] and abs(p[-2] - p[-4]) < (p[-1] * 0.002) and p[-3] < p[-2]:
        return "DOUBLE_TOP_M"
    return None


def analyze_market_structure(df):
    """État du marché : tendance ou range (M30 ou H1 recommandé)"""
    if len(df) < 50:
        return "INSUFFISANT", 0, 0

    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    current_adx = adx['ADX_14'].iloc[-1]

    resistance = df['high'].rolling(window=20).max().iloc[-1]
    support    = df['low'].rolling(window=20).min().iloc[-1]

    if current_adx < 22:
        return "ACCUMULATION (RANGE)", support, resistance

    ema = ta.ema(df['close'], length=50).iloc[-1]
    status = "HAUSSIÈRE" if df['close'].iloc[-1] > ema else "BAISSIÈRE"
    return status, support, resistance


def get_market_trend_h4():
    """Filtre de tendance haute timeframe (H4)"""
    df = get_price_data(SYMBOL, mt5.TIMEFRAME_H4, 100)
    if df.empty:
        return "NEUTRAL"
    df['ema_50'] = ta.ema(df['close'], length=EMA_PERIOD_H4)
    return "UP" if df['close'].iloc[-1] > df['ema_50'].iloc[-1] else "DOWN"


def check_fvg(df):
    """Fair Value Gap simple sur les 3 dernières bougies"""
    if len(df) < 3:
        return False, None
    if df['high'].iloc[-3] < df['low'].iloc[-1]:
        return True, "BULLISH"
    if df['low'].iloc[-3] > df['high'].iloc[-1]:
        return True, "BEARISH"
    return False, None


def analyze_amd_priority(symbol):
    """Priorise l'accumulation → manipulation sur les TF hautes"""
    tfs = [
        (mt5.TIMEFRAME_H4,  "H4"),
        (mt5.TIMEFRAME_H1,  "H1"),
        (mt5.TIMEFRAME_M30, "M30")
    ]

    for tf_val, tf_name in tfs:
        df = get_price_data(symbol, tf_val, 120)
        if df.empty:
            continue

        # Bandes de Bollinger → bandwidth faible = compression / accumulation
        bb = ta.bbands(df['close'], length=20, std=2)
        if 'BBU_20_2.0' not in bb.columns:
            continue

        bandwidth = (bb['BBU_20_2.0'] - bb['BBL_20_2.0']) / bb['BBM_20_2.0']
        avg_bandwidth = bandwidth.rolling(50).mean().iloc[-1]

        if bandwidth.iloc[-1] < avg_bandwidth * 0.80:
            # Range détecté → on cherche la manipulation (fakeout)
            high_range = df['high'].tail(15).max()
            low_range  = df['low'].tail(15).min()
            current_price = mt5.symbol_info_tick(symbol).ask

            if current_price < low_range - 0.1:   # fake breakdown → opportunité achat
                return {
                    "type": "BUY",
                    "reason": f"AMD_MANIPULATION_{tf_name}",
                    "tf": tf_name,
                    "context": "Accumulation → Fake breakdown"
                }
            elif current_price > high_range + 0.1:  # fake breakout → opportunité vente
                return {
                    "type": "SELL",
                    "reason": f"AMD_MANIPULATION_{tf_name}",
                    "tf": tf_name,
                    "context": "Accumulation → Fake breakout"
                }
    return None


def get_smart_signal():
    """
    Stratégie principale – Ordre de priorité :
      1. AMD Manipulation (H4 > H1 > M30)
      2. Figures chartistes W/M sur M5
      3. Rebond sur support dynamique M5
      4. (optionnel) Structure + OTE + FVG alignés
    """
    # ── 1. Priorité AMD Manipulation ─────────────────────────────────────
    amd_signal = analyze_amd_priority(SYMBOL)
    if amd_signal:
        logging.info(f"AMD PRIORITAIRE → {amd_signal['reason']}")
        return amd_signal

    # ── 2. Figures chartistes M5 ─────────────────────────────────────────
    df_m5 = get_price_data(SYMBOL, mt5.TIMEFRAME_M5, 200)
    if not df_m5.empty:
        pattern = detect_advanced_patterns(df_m5)
        if pattern:
            bias = "BUY" if "BOTTOM" in pattern else "SELL"
            return {
                "type": bias,
                "reason": pattern,
                "tf": "M5"
            }

    # ── 3. Rebond support / résistance dynamique M5 ───────────────────────
    if not df_m5.empty:
        current_p = mt5.symbol_info_tick(SYMBOL).ask
        dynamic_support = df_m5['low'].rolling(50).min().iloc[-1]
        if current_p <= dynamic_support * 1.0005:  # petite marge
            return {
                "type": "BUY",
                "reason": "DYNAMIC_SUPPORT_M5",
                "tf": "M5"
            }

    # ── 4. Stratégie classique Structure + OTE + FVG (si tu veux la garder) ──
    trend_h4 = get_market_trend_h4()
    df_m30 = get_price_data(SYMBOL, mt5.TIMEFRAME_M30, 300)
    if df_m30.empty:
        return None

    status, sup, res = analyze_market_structure(df_m30)
    has_fvg, fvg_type = check_fvg(df_m30)

    if status == "ACCUMULATION (RANGE)":
        return None

    current_p = mt5.symbol_info_tick(SYMBOL).ask
    recent_low  = df_m30['low'].tail(40).min()
    recent_high = df_m30['high'].tail(40).max()
    range_val   = recent_high - recent_low

    if range_val < 0.0001:  # protection division par zéro
        return None

    ote_buy  = recent_high - range_val * 0.705
    ote_sell = recent_low  + range_val * 0.705

    if (trend_h4 == "UP" and status == "HAUSSIÈRE" and
        current_p <= ote_buy + 0.0005 and has_fvg and fvg_type == "BULLISH"):
        return {
            "type": "BUY",
            "reason": "OTE+FVG_BULL_H4",
            "tf": "M30",
            "sl": recent_low - 0.0008 * 10,   # 8 pips sous swing low
            "tp": recent_high + 0.0010 * 10,
            "tp_half": recent_high
        }

    if (trend_h4 == "DOWN" and status == "BAISSIÈRE" and
        current_p >= ote_sell - 0.0005 and has_fvg and fvg_type == "BEARISH"):
        return {
            "type": "SELL",
            "reason": "OTE+FVG_BEAR_H4",
            "tf": "M30",
            "sl": recent_high + 0.0008 * 10,
            "tp": recent_low - 0.0010 * 10,
            "tp_half": recent_low
        }

    return None

def find_swings(df):
    """Identifie les fractales pour Fibonacci"""
    df['high_swing'] = df['high'][(df['high'] == df['high'].rolling(11, center=True).max())]
    df['low_swing'] = df['low'][(df['low'] == df['low'].rolling(11, center=True).min())]
    
    try:
        last_low = df['low_swing'].dropna().iloc[-1]
        last_high = df['high_swing'].dropna().iloc[-1]
        return last_low, last_high
    except IndexError:
        return None, None


def open_trade_v100(signal):
    """Exécute l'ordre et notifie la console/bot avec détails lot et prix"""
    tick = mt5.symbol_info_tick(SYMBOL)
    lot = float(max(MIN_LOT_V100, 1.0)) # Sécurité lot minimum
    
    price = tick.ask if signal['type'] == "BUY" else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if signal['type'] == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": float(signal['sl']),
        "tp": float(signal['tp']),
        "magic": MAGIC_NUMBER,
        "comment": "SMC_PRO_V100",
        "type_filling": mt5.ORDER_FILLING_FOK,
        "type_time": mt5.ORDER_TIME_GTC,
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = (f"🚀 POSITION {signal['type']} | Lot: {lot}\n"
               f"Entrée: {result.price:.2f}\nSL: {signal['sl']:.2f} | TP: {signal['tp']:.2f}")
        print(f"\n--- EXECUTION ---\n{msg}\n-----------------\n")
        send_telegram_alert(msg, force=True)
        save_open(result.order, signal['type'], result.price)
        return result.order, lot
    else:
        print(f"❌ Erreur ouverture : {result.comment}")
        return None, 0

def update_db_profit(ticket, profit, close_price, status="CLOSED"):
    """Met à jour MongoDB en ajoutant le profit (gère partiels et BE)"""
    collection.update_one(
        {"ticket": ticket},
        {"$inc": {"profit": float(profit)}, 
         "$set": {"close_price": float(close_price), "status": status, "close_time": datetime.utcnow()}}
    )

def handle_trade_closure(ticket, lot, reason):
    """Notification finale lors du SL ou TP avec profit réel BD"""
    # Attendre la synchro historique
    time.sleep(1)
    history = mt5.history_deals_get(position=ticket)
    if history:
        total_profit = sum(deal.profit for deal in history)
        msg = (f"🏁 TRADE TERMINE ({reason})\nTicket: {ticket} | Lot: {lot}\n"
               f"Résultat Final: {total_profit:.2f} USD")
        print(f"\n--- CLOTURE ---\n{msg}\n---------------\n")
        send_telegram_alert(msg, force=True)

def close_partial_v100(ticket, vol):
    """Ferme 50% et notifie le retrait partiel"""
    pos_list = mt5.positions_get(ticket=ticket)
    if not pos_list: return False
    
    pos = pos_list[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": float(vol),
        "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "position": ticket,
        "price": tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask,
        "magic": MAGIC_NUMBER,
        "comment": "PARTIEL 50%",
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        time.sleep(0.5)
        deal = mt5.history_deals_get(ticket=result.order)[0]
        update_db_profit(ticket, deal.profit, result.price, status="PARTIAL_TAKEN")
        msg = f"💰 PARTIEL ENCAISSÉ : +{deal.profit:.2f} USD pour le ticket {ticket}"
        print(msg)
        send_telegram_alert(msg)
        return True
    return False

def move_sl_to_be(ticket):
    """Déplace le SL au prix d'entrée (Break-Even)"""
    pos_list = mt5.positions_get(ticket=ticket)
    if not pos_list: return False
    
    pos = pos_list[0]
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl": pos.price_open,
        "tp": pos.tp
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = f"🛡️ BREAK-EVEN : SL sécurisé à {pos.price_open} pour {ticket}"
        print(msg)
        send_telegram_alert(msg)
        return True
    return False

def is_volatility_good():
    """Vérifie l'heure et la volatilité via l'ATR"""
    now = datetime.utcnow().hour
    
    # 1. Vérification Horaire
    if not (START_HOUR <= now < END_HOUR):
        msg = f"⏳ Marché hors session : {now}h GMT. Bonne volatilité entre {START_HOUR}h et {END_HOUR}h GMT."
        return False, msg

    # 2. Vérification Technique (ATR)
    df = get_price_data(SYMBOL, mt5.TIMEFRAME_M5, 50)
    if df.empty: return False, "Données indisponibles"
    
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    current_atr = atr.iloc[-1]
    avg_atr = atr.mean()

    # Si la volatilité actuelle est 20% sous la moyenne, on évite
    if current_atr < (avg_atr * 0.8):
        msg = f"📉 Volatilité trop faible (ATR: {current_atr:.2f}). Le marché dort."
        return False, msg

    return True, "Volatilité OK"

def detect_chart_patterns(df):
    """Détecte les figures chartistes redoutables (W, M, ETE)"""
    if len(df) < 20: return None
    
    last_prices = df['close'].values
    highs = df['high'].values
    lows = df['low'].values

    # 1. Double Bas (W) / Double Sommet (M)
    # On compare les derniers creux/sommets locaux
    if lows[-1] > lows[-5] and abs(lows[-5] - lows[-10]) < (lows[-1] * 0.001):
        return "DOUBLE_BOTTOM"
    if highs[-1] < highs[-5] and abs(highs[-5] - highs[-10]) < (highs[-1] * 0.001):
        return "DOUBLE_TOP"

    # 2. Détection de Triangle (Compression de volatilité)
    atr = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
    if atr < ta.atr(df['high'], df['low'], df['close'], length=14).mean() * 0.6:
        return "TRIANGLE_COMPRESSION"

    return None

def analyze_amd_cycle(symbol, timeframe):
    """Logique Accumulation - Manipulation - Distribution"""
    df = get_price_data(symbol, timeframe, 100)
    if df.empty: return None
    
    # 1. Accumulation : Range étroit et volume faible
    std_dev = df['close'].tail(20).std()
    avg_std = df['close'].rolling(50).std().mean()
    
    is_accumulating = std_dev < (avg_std * 0.7)
    
    if is_accumulating:
        # On définit les bornes du range
        high_range = df['high'].tail(20).max()
        low_range = df['low'].tail(20).min()
        
        # 2. Manipulation : Le prix casse le range puis réintègre brutalement
        current_price = mt5.symbol_info_tick(symbol).ask
        
        # Exemple Manipulation Haussière (on casse le bas pour acheter)
        if current_price < low_range:
            return {"phase": "MANIPULATION", "bias": "BUY", "level": low_range}
            
    return None

def get_best_timeframe_amd():
    """Cherche l'accumulation sur les TF les plus hautes en priorité"""
    timeframes = [
        (mt5.TIMEFRAME_H4, "H4"),
        (mt5.TIMEFRAME_H1, "H1"),
        (mt5.TIMEFRAME_M30, "M30")
    ]
    
    for tf, name in timeframes:
        amd_data = analyze_amd_cycle(SYMBOL, tf)
        if amd_data:
            print(f"💎 Accumulation majeure détectée sur {name}. Priorité AMD activée.")
            return tf, amd_data
            
    return None, None

