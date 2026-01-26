import time
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
import numpy as np
import logging
from datetime import datetime

from database import save_open, collection
from utils import send_telegram_alert
from config import SYMBOL, MAGIC_NUMBER

# ─── PARAMÈTRES TECHNIQUES ────────────────────────────────────────────────
EMA_PERIOD_H4    = 50
MAX_ALLOWED_SPREAD = 0.60

def get_price_data(symbol, timeframe, n_bars=400):
    """Récupère les données OHLCV pour un symbole spécifique"""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
    if rates is None or len(rates) == 0:
        logging.warning(f"Données indisponibles pour {symbol} en TF {timeframe}")
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def get_dynamic_lot(symbol, risk_percent=0.01):
    """Calcule le lot minimal ou basé sur le risque pour chaque indice"""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return 0.1
    
    # Pour les indices synthétiques, on commence souvent par le lot minimal autorisé
    # car la volatilité est déjà intrinsèquement élevée.
    min_lot = symbol_info.volume_min
    return min_lot

def get_zigzag(df, depth=10):
    """Calcule les points hauts et bas (ZigZag) avec sécurité"""
    try:
        zz_df = ta.zigzag(df['high'], df['low'], depth=depth)
        zigzag_col = None
        for col in zz_df.columns:
            if col.startswith('ZIGZAGs'):
                zigzag_col = col
                break
        
        if zigzag_col is None:
            df['zz'] = np.nan
        else:
            df['zz'] = zz_df[zigzag_col]
        
        peaks = df.dropna(subset=['zz']).copy()
        return peaks
    except Exception as e:
        logging.error(f"Erreur ZigZag : {e}")
        return pd.DataFrame()

def detect_advanced_patterns(symbol, df):
    """Détection W / M via ZigZag adaptée au symbole"""
    peaks = get_zigzag(df, depth=6)
    if len(peaks) < 5:
        return None

    p = peaks['zz'].values
    # Seuil de tolérance adapté à la volatilité de l'indice
    tolerance = p[-1] * 0.002 

    # Double Bottom (W)
    if p[-1] > p[-2] and abs(p[-2] - p[-4]) < tolerance and p[-3] > p[-2]:
        return "DOUBLE_BOTTOM_W"
    
    # Double Top (M)
    if p[-1] < p[-2] and abs(p[-2] - p[-4]) < tolerance and p[-3] < p[-2]:
        return "DOUBLE_TOP_M"

    return None

def get_market_trend_h4(symbol):
    """Filtre de tendance haute timeframe (H4) pour un symbole"""
    df = get_price_data(symbol, mt5.TIMEFRAME_H4, 200)
    if df.empty: return "NEUTRAL"
    
    df['ema_50'] = ta.ema(df['close'], length=EMA_PERIOD_H4)
    if df['ema_50'].isna().all(): return "NEUTRAL"
    
    trend = "UP" if df['close'].iloc[-1] > df['ema_50'].iloc[-1] else "DOWN"
    return trend

def analyze_amd_priority(symbol):
    """Logique Accumulation -> Manipulation sur H1 avec gestion d'erreur robuste"""
    # Augmenter le nombre de bougies pour être sûr d'avoir assez de data
    df = get_price_data(symbol, mt5.TIMEFRAME_H1, 200) 
    if df.empty or len(df) < 50: 
        return None

    # Calcul des Bandes de Bollinger
    bb = ta.bbands(df['close'], length=20, std=2)
    
    # Correction : On cherche les colonnes dynamiquement pour éviter l'erreur de nom
    if bb is None or bb.empty:
        return None
        
    # On récupère les noms exacts des colonnes générées
    col_upper = [c for c in bb.columns if c.startswith('BBU')][0]
    col_lower = [c for c in bb.columns if c.startswith('BBL')][0]
    col_mid   = [c for c in bb.columns if c.startswith('BBM')][0]

    # Calcul de la compression (Accumulation)
    bandwidth = (bb[col_upper] - bb[col_lower]) / bb[col_mid]
    avg_bandwidth = bandwidth.rolling(30).mean().iloc[-1]
    
    # Si les données sont NaN (pas assez de recul), on sort
    if pd.isna(avg_bandwidth):
        return None

    if bandwidth.iloc[-1] < avg_bandwidth * 0.85:
        # On définit le range sur les 10 dernières bougies
        high_range = df['high'].tail(10).max()
        low_range  = df['low'].tail(10).min()
        tick = mt5.symbol_info_tick(symbol)
        
        if not tick: return None
        
        if tick.ask < low_range: # Fake breakdown (Manipulation)
            return {"type": "BUY", "reason": "AMD_MANIP_BUY", "tf": "H1"}
        elif tick.bid > high_range: # Fake breakout (Manipulation)
            return {"type": "SELL", "reason": "AMD_MANIP_SELL", "tf": "H1"}
            
    return None

def analyze_market_structure(df):
    """État du marché : tendance ou range (M30 ou H1 recommandé)"""
    logging.info(f"[MARKET STRUCTURE] Analyse sur {len(df)} bougies")
    if len(df) < 50:
        logging.warning("[MARKET STRUCTURE] Données insuffisantes pour analyse.")
        return "INSUFFISANT", 0, 0

    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    current_adx = adx['ADX_14'].iloc[-1]
    logging.info(f"[MARKET STRUCTURE] ADX actuel : {current_adx:.2f}")

    resistance = df['high'].rolling(window=20).max().iloc[-1]
    support    = df['low'].rolling(window=20).min().iloc[-1]
    logging.info(f"[MARKET STRUCTURE] Support: {support:.5f} | Résistance: {resistance:.5f}")
    if current_adx < 22:
        logging.info("[MARKET STRUCTURE] Marché en ACCUMULATION (RANGE) détecté.")
        return "ACCUMULATION (RANGE)", support, resistance

    ema = ta.ema(df['close'], length=50).iloc[-1]
    status = "HAUSSIÈRE" if df['close'].iloc[-1] > ema else "BAISSIÈRE"
    logging.info(f"[MARKET STRUCTURE] Tendance détectée : {status} | (EMA50: {ema:.5f})")
    return status, support, resistance


def check_fvg(df, lookback=5, min_gap=0.50):
    logging.info("[FVG] Vérification Fair Value Gap")
    """Fair Value Gap simple sur les 3 dernières bougies"""
    if len(df) < 3:
        logging.warning("[FVG] Données insuffisantes pour analyse FVG. Pas assezde de bougies.")
        return False, None
    if df['high'].iloc[-3] < df['low'].iloc[-1]:
        logging.info("[FVG] Fair Value Gap BULLISH détecté.")
        logging.info(f"[FVG] Gap détecté → zone : {df['high'].iloc[-3]:.5f} - {df['low'].iloc[-1]:.5f}")
        return True, "BULLISH"
    if df['low'].iloc[-3] > df['high'].iloc[-1]:
        logging.info("[FVG] Fair Value Gap BEARISH détecté.")
        logging.info(f"[FVG] Gap détecté → zone : {df['low'].iloc[-3]:.5f} - {df['high'].iloc[-1]:.5f}")
        return True, "BEARISH"
    logging.info("[FVG] Aucun Fair Value Gap détecté.")
    return False, None

def get_smart_signal(symbol):
    """Analyse complète pour un symbole donné"""
    tick = mt5.symbol_info_tick(symbol)
    if not tick: return None

    # 1. Priorité AMD
    amd = analyze_amd_priority(symbol)
    if amd: return amd

    # 2. Figures Chartistes H1
    df_h1 = get_price_data(symbol, mt5.TIMEFRAME_H1, 200)
    pattern = detect_advanced_patterns(symbol, df_h1)
    if pattern:
        return {"type": "BUY" if "BOTTOM" in pattern else "SELL", "reason": pattern, "tf": "H1"}

    # 3. Structure SMC (OTE + Trend)
    trend = get_market_trend_h4(symbol)
    df_m15 = get_price_data(symbol, mt5.TIMEFRAME_M15, 100)
    if df_m15.empty: return None

    recent_low = df_m15['low'].tail(30).min()
    recent_high = df_m15['high'].tail(30).max()
    range_val = recent_high - recent_low
    
    if trend == "UP" and tick.ask <= recent_high - (range_val * 0.705):
        return {
            "type": "BUY", "reason": "SMC_OTE_BUY", "tf": "M15",
            "sl": recent_low - (range_val * 0.1),
            "tp": recent_high + (range_val * 0.5),
            "tp_half": recent_high
        }
    
    if trend == "DOWN" and tick.bid >= recent_low + (range_val * 0.705):
        return {
            "type": "SELL", "reason": "SMC_OTE_SELL", "tf": "M15",
            "sl": recent_high + (range_val * 0.1),
            "tp": recent_low - (range_val * 0.5),
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

def update_db_profit(ticket, profit, close_price, status="CLOSED"):
    """Met à jour MongoDB en ajoutant le profit (gère partiels et BE)"""
    collection.update_one(
        {"ticket": ticket},
        {"$inc": {"profit": float(profit)}, 
         "$set": {"close_price": float(close_price), "status": status, "close_time": datetime.utcnow()}}
    )

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
    df = get_price_data(symbol, timeframe, 400)
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
    ]
    
    for tf, name in timeframes:
        amd_data = analyze_amd_cycle(SYMBOL, tf)
        if amd_data:
            print(f"💎 Accumulation majeure détectée sur {name}. Priorité AMD activée.")
            return tf, amd_data
            
    return None, None

def move_sl_to_be(symbol, ticket):
    """Sécurise la position au prix d'entrée (Break-Even)"""
    pos = mt5.positions_get(ticket=ticket)
    if not pos: return False
    
    p = pos[0]
    # Si le SL est déjà au prix d'entrée, on ne fait rien
    if p.sl == p.price_open: return True

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": ticket,
        "sl": float(p.price_open),
        "tp": float(p.tp)
    }
    
    res = mt5.order_send(request)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"🛡️ [{symbol}] SL déplacé au Break-Even pour {ticket}")
        return True
    else:
        logging.error(f"❌ Erreur BE sur {symbol}: {res.comment}")
        return False
    
def monitor_active_trade(symbol, ticket, lot, signal_data):
    """Surveille une position spécifique et gère le cycle de vie complet"""
    half_done = False
    logging.info(f"👀 [{symbol}] Surveillance active du ticket {ticket}...")

    while True:
        positions = mt5.positions_get(ticket=ticket)
        
        # SI LA POSITION N'EXISTE PLUS (Clôture Totale)
        if not positions:
            time.sleep(1) # Attendre que l'historique se mette à jour
            history = mt5.history_deals_get(ticket=ticket)
            
            total_profit = 0
            exit_price = 0
            if history:
                total_profit = sum(deal.profit for deal in history)
                exit_price = history[-1].price
            
            status = "✅ TP TOUCHÉ" if total_profit > 0 else "❌ SL TOUCHÉ"
            
            msg = (
                f"🏁 **POSITION FERMÉE**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 **Statut:** {status}\n"
                f"📈 **Marché:** {symbol}\n"
                f"💰 Profit/Perte Total: {total_profit:.2f} USD\n"
                f"Prix Sortie: {exit_price}\n"
                f"Lot total géré: {lot}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram_alert(msg)
            handle_trade_closure(symbol, ticket, lot, status)
            break
        
        # GESTION EN COURS (BE et Partiel)
        pos = positions[0]
        current_price = pos.price_current
        
        if not half_done and 'tp_half' in signal_data:
            target_reached = False
            if pos.type == mt5.ORDER_TYPE_BUY:
                target_reached = current_price >= signal_data['tp_half']
            elif pos.type == mt5.ORDER_TYPE_SELL:
                target_reached = current_price <= signal_data['tp_half']
            
            if target_reached:
                logging.info(f"🎯 [{symbol}] Objectif partiel atteint.")
                # On ferme 50% du volume actuel
                if close_partial(symbol, ticket, pos.volume / 2):
                    if move_sl_to_be(symbol, ticket):
                        half_done = True
                        # Le message de succès est déjà envoyé par close_partial
        
        time.sleep(1)
        
    

def monitor_active_trade(symbol, ticket, lot, signal_data):
    """Surveille une position spécifique sans bloquer les autres analyses"""
    half_done = False
    logging.info(f"👀 [{symbol}] Surveillance active du ticket {ticket}...")

    while True:
        positions = mt5.positions_get(ticket=ticket)
        
        if not positions:
            handle_trade_closure(symbol, ticket, lot, "SL/TP SERVEUR")
            break
        
        pos = positions[0]
        current_price = pos.price_current
        
        if not half_done:
            target_reached = False
            if pos.type == mt5.ORDER_TYPE_BUY:
                
                target_reached = current_price >= signal_data['tp_half']
            elif pos.type == mt5.ORDER_TYPE_SELL:
                target_reached = current_price <= signal_data['tp_half']
            
            if target_reached:
                logging.info(f"🎯 [{symbol}] Objectif partiel atteint.")
                if close_partial(symbol, ticket, pos.volume / 2):
                    if move_sl_to_be(symbol, ticket):
                        half_done = True
                        send_telegram_alert(f"🛡️ [{symbol}] Partiel encaissé et BE activé.")

        time.sleep(1)


def close_partial(symbol, ticket, vol):
    """Clôture partielle sécurisée avec reporting de profit"""
    pos = mt5.positions_get(ticket=ticket)
    if not pos: return False
    
    tick = mt5.symbol_info_tick(symbol)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(vol),
        "type": mt5.ORDER_TYPE_SELL if pos[0].type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "position": ticket,
        "price": tick.bid if pos[0].type == mt5.ORDER_TYPE_BUY else tick.ask,
        "magic": MAGIC_NUMBER,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    
    res = mt5.order_send(request)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        time.sleep(0.5)  # Petit délai pour laisser MT5 enregistrer le deal
        # Récupération du deal pour avoir le profit réel encaissé
        history = mt5.history_deals_get(ticket=ticket)
        partial_profit = 0
        if history:
            # On prend le dernier deal (celui de la clôture partielle)
            partial_profit = history[-1].profit
            
        update_db_profit(ticket, partial_profit, res.price, status="PARTIAL_TAKEN")
        
        msg = (
            f"💰 **PARTIEL ENCAISSÉ**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 **Marché:** {symbol}\n"
            f"Ticket: {ticket}\n"
            f"Profit: +{partial_profit:.2f} USD\n"
            f"Volume restant: {pos[0].volume - vol}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_alert(msg)
        return True
    return False

def is_volatility_good(symbol):
    """Vérifie si l'indice est assez 'excité' pour être tradé"""
    df = get_price_data(symbol, mt5.TIMEFRAME_H1, 50)
    if df.empty: return False, "Pas de data"
    
    atr = ta.atr(df['high'], df['low'], df['close'], length=14)
    if atr is None or len(atr) < 1: return False, "ATR Error"
    
    current_atr = atr.iloc[-1]
    avg_atr = atr.mean()

    if current_atr < (avg_atr * 0.7):
        return False, f"{symbol} trop calme"
    return True, "OK"

def handle_trade_closure(symbol, ticket, lot, reason):
    """Gère la fin d'un trade et log le résultat"""
    logging.info(f"🏁 [{symbol}] Position {ticket} fermée ({reason})")
    send_telegram_alert(f"🏁 [{symbol}] Trade fermé : {reason}")
    
def open_trade(symbol, signal):
    """Exécution d'ordre universelle pour Indices Synthétiques avec rapport complet"""
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        logging.error(f"Impossible de récupérer le tick pour {symbol}")
        return None, 0
        
    lot = get_dynamic_lot(symbol)
    price = tick.ask if signal['type'] == "BUY" else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": mt5.ORDER_TYPE_BUY if signal['type'] == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": float(signal['sl']),
        "tp": float(signal['tp']),
        "magic": MAGIC_NUMBER,
        "comment": f"BOT_{symbol[:3]}",
        "type_filling": mt5.ORDER_FILLING_FOK,
        "type_time": mt5.ORDER_TIME_GTC,
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        # Message Telegram de Bienvenue sur le Marché
        msg = (
            f"🔔 **NOUVELLE POSITION OUVERTE**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 **Marché:** {symbol}\n"
            f"Type: {'🔵 BUY' if signal['type'] == 'BUY' else '🔴 SELL'}\n"
            f"Lot: {lot}\n"
            f"Prix Entrée: {result.price}\n"
            f"🚫 SL: {signal['sl']}\n"
            f"🟡 Middle TP (50%): {signal.get('tp_half', 'N/A')}\n"
            f"🎯 TP Final: {signal['tp']}\n"
            f"💡 **Raison:** {signal['reason']}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_alert(msg)
        save_open(result.order, signal['type'], result.price)
        return result.order, lot
    else:
        logging.error(f"Échec {symbol}: {result.comment}")
        return None, 0