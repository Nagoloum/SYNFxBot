"""
STRATÉGIE DE CONFIRMATION DE STRUCTURE
=======================================
Philosophie : Ne trader que les mouvements explosifs confirmés
- Filtre de tendance M5 (EMA 50)
- Filtre de sécurité M1 (EMA 200)
- Signal de croisement M1 (EMA 9 x EMA 21)
- Confirmation de cassure (Donchian Channel)
- Filtres de puissance (ADX, RSI)
- Sizing intelligent (Squeeze)
- Sortie dynamique (Chandelier Exit)
"""

import time
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
import numpy as np
import logging
from datetime import datetime

from database import save_open, save_close
from utils import send_telegram_alert
from config import SYMBOL, MAGIC_NUMBER, ACCOUNT_NUMBER

# ═══════════════════════════════════════════════════════════════
# PARAMÈTRES DE LA STRATÉGIE
# ═══════════════════════════════════════════════════════════════

# Timeframes
TIMEFRAME_M5 = mt5.TIMEFRAME_M5
TIMEFRAME_M1 = mt5.TIMEFRAME_M1

# Indicateurs M5 (Contexte)
EMA_M5_PERIOD = 50

# Indicateurs M1 (Exécution)
EMA_M1_KING = 200      # King Filter
EMA_M1_FAST = 9        # Signal rapide
EMA_M1_SLOW = 21       # Signal lent

# Donchian Channel
DONCHIAN_PERIOD = 20

# ADX (Puissance)
ADX_PERIOD = 14
ADX_THRESHOLD = 20

# RSI (Momentum)
RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 55
RSI_SELL_THRESHOLD = 45

# Bollinger Bands (Squeeze Detection)
BB_PERIOD = 20
BB_STD = 2

# ATR (Chandelier Exit)
ATR_PERIOD = 14
ATR_MULTIPLIER = 3.0    # Distance du Trailing Stop

# Money Management
RISK_PER_TRADE = 0.01   # 1% du capital par trade
SQUEEZE_SIZE_MULTIPLIER = 1.5  # Multiplie la taille si squeeze détecté
EXPANSION_SIZE_MULTIPLIER = 0.5  # Réduit la taille si expansion déjà faite

# Seuils Squeeze
SQUEEZE_THRESHOLD = 0.85  # BBW < 85% de la moyenne = Squeeze


# ═══════════════════════════════════════════════════════════════
# FONCTIONS UTILITAIRES
# ═══════════════════════════════════════════════════════════════

def get_price_data(symbol, timeframe, bars=500):
    """Récupère les données de prix"""
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df
    except Exception as e:
        logging.error(f"Erreur get_price_data {symbol}: {e}")
        return pd.DataFrame()


def get_dynamic_lot(symbol, entry_price, sl_price, risk_percent=RISK_PER_TRADE):
    """
    Calcule le lot en fonction du risque autorisé
    
    Args:
        symbol: Symbole tradé
        entry_price: Prix d'entrée
        sl_price: Prix du Stop Loss
        risk_percent: % du capital à risquer
    
    Returns:
        float: Lot optimal
    """
    account_info = mt5.account_info()
    if not account_info:
        return 0.1
    
    balance = account_info.balance
    risk_amount = balance * risk_percent
    
    # Distance du SL en points
    distance_sl = abs(entry_price - sl_price)
    if distance_sl == 0:
        return 0.1
    
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        return 0.1
    
    # Calcul du lot : Risque / (Distance SL * Valeur du point)
    point_value = symbol_info.trade_tick_value
    lot = risk_amount / (distance_sl * point_value)
    
    # Arrondi au lot minimum autorisé
    lot_min = symbol_info.volume_min
    lot_max = symbol_info.volume_max
    lot_step = symbol_info.volume_step
    
    lot = max(lot_min, min(lot_max, round(lot / lot_step) * lot_step))
    
    return float(lot)


# ═══════════════════════════════════════════════════════════════
# CALCUL DES INDICATEURS
# ═══════════════════════════════════════════════════════════════

def calculate_ema(df, period):
    """Calcule l'EMA"""
    ema = ta.ema(df['close'], length=period)
    return ema


def calculate_donchian(df, period=DONCHIAN_PERIOD):
    """
    Calcule le Canal de Donchian
    
    Returns:
        tuple: (upper_band, lower_band)
    """
    upper_band = df['high'].rolling(window=period).max()
    lower_band = df['low'].rolling(window=period).min()
    return upper_band, lower_band


def calculate_adx(df, period=ADX_PERIOD):
    """Calcule l'ADX"""
    adx_data = ta.adx(df['high'], df['low'], df['close'], length=period)
    if adx_data is None or adx_data.empty:
        return None
    
    # Retourne la colonne ADX
    adx_col = [c for c in adx_data.columns if c.startswith('ADX')][0]
    return adx_data[adx_col]


def calculate_rsi(df, period=RSI_PERIOD):
    """Calcule le RSI"""
    rsi = ta.rsi(df['close'], length=period)
    return rsi


def calculate_bollinger_bands(df, period=BB_PERIOD, std=BB_STD):
    """
    Calcule les Bandes de Bollinger et le BBW (Bandwidth)
    
    Returns:
        dict: {'upper', 'middle', 'lower', 'bbw'}
    """
    bb = ta.bbands(df['close'], length=period, std=std)
    if bb is None or bb.empty:
        return None
    
    col_upper = [c for c in bb.columns if c.startswith('BBU')][0]
    col_lower = [c for c in bb.columns if c.startswith('BBL')][0]
    col_mid = [c for c in bb.columns if c.startswith('BBM')][0]
    
    # Calcul du Bandwidth (Largeur relative)
    bbw = (bb[col_upper] - bb[col_lower]) / bb[col_mid]
    
    return {
        'upper': bb[col_upper],
        'middle': bb[col_mid],
        'lower': bb[col_lower],
        'bbw': bbw
    }


def calculate_atr(df, period=ATR_PERIOD):
    """Calcule l'ATR"""
    atr = ta.atr(df['high'], df['low'], df['close'], length=period)
    return atr


# ═══════════════════════════════════════════════════════════════
# DÉTECTION DU SQUEEZE
# ═══════════════════════════════════════════════════════════════

def detect_squeeze(df):
    """
    Détecte si le marché est en état de Squeeze (compression)
    
    Returns:
        dict: {'is_squeeze': bool, 'multiplier': float}
    """
    bb = calculate_bollinger_bands(df)
    if bb is None:
        return {'is_squeeze': False, 'multiplier': 1.0}
    
    # Moyenne du BBW sur 30 périodes
    avg_bbw = bb['bbw'].rolling(30).mean().iloc[-1]
    current_bbw = bb['bbw'].iloc[-1]
    
    if pd.isna(avg_bbw) or pd.isna(current_bbw):
        return {'is_squeeze': False, 'multiplier': 1.0}
    
    # Squeeze : BBW actuel < 85% de la moyenne
    if current_bbw < avg_bbw * SQUEEZE_THRESHOLD:
        logging.info(f"🔥 SQUEEZE DÉTECTÉ | BBW actuel: {current_bbw:.6f} < Moyenne: {avg_bbw:.6f}")
        return {'is_squeeze': True, 'multiplier': SQUEEZE_SIZE_MULTIPLIER}
    
    # Expansion déjà faite : BBW actuel > 115% de la moyenne
    elif current_bbw > avg_bbw * 1.15:
        logging.info(f"⚠️ EXPANSION DÉTECTÉE | BBW actuel: {current_bbw:.6f} > Moyenne: {avg_bbw:.6f}")
        return {'is_squeeze': False, 'multiplier': EXPANSION_SIZE_MULTIPLIER}
    
    return {'is_squeeze': False, 'multiplier': 1.0}


# ═══════════════════════════════════════════════════════════════
# LOGIQUE DE SIGNAL
# ═══════════════════════════════════════════════════════════════

def get_market_context_m5(symbol):
    """
    Filtre de Tendance M5 via EMA 50
    
    Returns:
        str: 'UP' / 'DOWN' / 'NEUTRAL'
    """
    df_m5 = get_price_data(symbol, TIMEFRAME_M5, 100)
    if df_m5.empty or len(df_m5) < EMA_M5_PERIOD + 5:
        return 'NEUTRAL'
    
    ema50 = calculate_ema(df_m5, EMA_M5_PERIOD)
    if ema50 is None or ema50.empty:
        return 'NEUTRAL'
    
    last_close = df_m5['close'].iloc[-1]
    last_ema = ema50.iloc[-1]
    
    if last_close > last_ema:
        return 'UP'
    elif last_close < last_ema:
        return 'DOWN'
    return 'NEUTRAL'


def check_m1_filters(symbol, signal_type):
    """
    Vérifie les filtres M1 :
    - EMA 200 (King Filter)
    - ADX > 20
    - RSI > 55 (BUY) ou < 45 (SELL)
    
    Returns:
        bool: True si tous les filtres passent
    """
    df_m1 = get_price_data(symbol, TIMEFRAME_M1, 250)
    if df_m1.empty or len(df_m1) < EMA_M1_KING + 5:
        return False
    
    # Prix actuel
    current_price = df_m1['close'].iloc[-1]
    
    # 1. King Filter (EMA 200)
    ema200 = calculate_ema(df_m1, EMA_M1_KING)
    if ema200 is None or ema200.empty:
        return False
    
    last_ema200 = ema200.iloc[-1]
    
    if signal_type == 'BUY':
        if current_price <= last_ema200:
            logging.debug(f"❌ King Filter : Prix {current_price:.5f} <= EMA200 {last_ema200:.5f}")
            return False
    else:  # SELL
        if current_price >= last_ema200:
            logging.debug(f"❌ King Filter : Prix {current_price:.5f} >= EMA200 {last_ema200:.5f}")
            return False
    
    # 2. ADX > 20
    adx = calculate_adx(df_m1, ADX_PERIOD)
    if adx is None or adx.empty:
        return False
    
    last_adx = adx.iloc[-1]
    if last_adx <= ADX_THRESHOLD:
        logging.debug(f"❌ ADX faible : {last_adx:.2f} <= {ADX_THRESHOLD}")
        return False
    
    # 3. RSI
    rsi = calculate_rsi(df_m1, RSI_PERIOD)
    if rsi is None or rsi.empty:
        return False
    
    last_rsi = rsi.iloc[-1]
    
    if signal_type == 'BUY':
        if last_rsi <= RSI_BUY_THRESHOLD:
            logging.debug(f"❌ RSI faible pour BUY : {last_rsi:.2f} <= {RSI_BUY_THRESHOLD}")
            return False
    else:  # SELL
        if last_rsi >= RSI_SELL_THRESHOLD:
            logging.debug(f"❌ RSI élevé pour SELL : {last_rsi:.2f} >= {RSI_SELL_THRESHOLD}")
            return False
    
    logging.info(f"✅ Filtres M1 validés | EMA200: {last_ema200:.5f}, ADX: {last_adx:.2f}, RSI: {last_rsi:.2f}")
    return True


def detect_ema_cross_and_donchian_break(symbol):
    """
    Détecte le signal TRIGGER :
    - Croisement EMA 9 x EMA 21
    - ET Cassure du Canal de Donchian
    
    Returns:
        dict or None: Signal avec type, entry, sl, tp, reason
    """
    df_m1 = get_price_data(symbol, TIMEFRAME_M1, 100)
    if df_m1.empty or len(df_m1) < max(EMA_M1_SLOW, DONCHIAN_PERIOD) + 5:
        return None
    
    # Calcul des EMAs
    ema9 = calculate_ema(df_m1, EMA_M1_FAST)
    ema21 = calculate_ema(df_m1, EMA_M1_SLOW)
    
    if ema9 is None or ema21 is None or ema9.empty or ema21.empty:
        return None
    
    # Calcul du Donchian
    donchian_upper, donchian_lower = calculate_donchian(df_m1, DONCHIAN_PERIOD)
    
    # Données actuelles et précédentes
    current_close = df_m1['close'].iloc[-1]
    current_ema9 = ema9.iloc[-1]
    current_ema21 = ema21.iloc[-1]
    prev_ema9 = ema9.iloc[-2]
    prev_ema21 = ema21.iloc[-2]
    
    donchian_high = donchian_upper.iloc[-1]
    donchian_low = donchian_lower.iloc[-1]
    
    # Calcul ATR pour le SL
    atr = calculate_atr(df_m1, ATR_PERIOD)
    if atr is None or atr.empty:
        return None
    current_atr = atr.iloc[-1]
    
    # ──────────────────────────────────────────────────────────
    # SIGNAL BUY
    # ──────────────────────────────────────────────────────────
    # Condition 1 : Croisement haussier EMA 9 > EMA 21
    ema_bullish_cross = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
    
    # Condition 2 : Cassure Donchian (prix clôture au-dessus du plus haut)
    donchian_break_up = current_close > donchian_high
    
    if ema_bullish_cross and donchian_break_up:
        # Calcul SL et TP
        sl = current_close - (ATR_MULTIPLIER * current_atr)
        tp = current_close + (ATR_MULTIPLIER * current_atr * 3)  # Ratio 1:3
        
        return {
            'type': 'BUY',
            'entry_price': current_close,
            'sl': sl,
            'tp': tp,
            'reason': 'EMA_CROSS_UP_DONCHIAN_BREAK',
            'ema9': current_ema9,
            'ema21': current_ema21,
            'donchian_high': donchian_high,
            'atr': current_atr
        }
    
    # ──────────────────────────────────────────────────────────
    # SIGNAL SELL
    # ──────────────────────────────────────────────────────────
    # Condition 1 : Croisement baissier EMA 9 < EMA 21
    ema_bearish_cross = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)
    
    # Condition 2 : Cassure Donchian (prix clôture en-dessous du plus bas)
    donchian_break_down = current_close < donchian_low
    
    if ema_bearish_cross and donchian_break_down:
        # Calcul SL et TP
        sl = current_close + (ATR_MULTIPLIER * current_atr)
        tp = current_close - (ATR_MULTIPLIER * current_atr * 3)
        
        return {
            'type': 'SELL',
            'entry_price': current_close,
            'sl': sl,
            'tp': tp,
            'reason': 'EMA_CROSS_DOWN_DONCHIAN_BREAK',
            'ema9': current_ema9,
            'ema21': current_ema21,
            'donchian_low': donchian_low,
            'atr': current_atr
        }
    
    return None


def get_smart_signal(symbol):
    """
    Signal Principal de la Stratégie
    Combine tous les filtres et détections
    
    Returns:
        dict or None: Signal complet si toutes les conditions sont remplies
    """
    # ÉTAPE 1 : Contexte M5 (Tendance globale)
    context = get_market_context_m5(symbol)
    if context == 'NEUTRAL':
        return None
    
    logging.debug(f"📊 Contexte M5 : {context}")
    
    # ÉTAPE 2 : Détection du signal TRIGGER (EMA Cross + Donchian)
    trigger = detect_ema_cross_and_donchian_break(symbol)
    if trigger is None:
        return None
    
    # ÉTAPE 3 : Vérification alignement contexte M5 vs signal M1
    if context == 'UP' and trigger['type'] != 'BUY':
        logging.debug(f"❌ Désalignement : Contexte {context} vs Signal {trigger['type']}")
        return None
    
    if context == 'DOWN' and trigger['type'] != 'SELL':
        logging.debug(f"❌ Désalignement : Contexte {context} vs Signal {trigger['type']}")
        return None
    
    # ÉTAPE 4 : Filtres M1 (King Filter, ADX, RSI)
    if not check_m1_filters(symbol, trigger['type']):
        return None
    
    # ÉTAPE 5 : Détection Squeeze (ajustement sizing)
    df_m1 = get_price_data(symbol, TIMEFRAME_M1, 100)
    squeeze_info = detect_squeeze(df_m1)
    trigger['size_multiplier'] = squeeze_info['multiplier']
    trigger['is_squeeze'] = squeeze_info['is_squeeze']
    
    logging.info(f"🎯 SIGNAL VALIDÉ | {symbol} | {trigger['type']} | {trigger['reason']}")
    logging.info(f"   Entry: {trigger['entry_price']:.5f} | SL: {trigger['sl']:.5f} | TP: {trigger['tp']:.5f}")
    logging.info(f"   Size Multiplier: {trigger['size_multiplier']}x")
    
    return trigger


# ═══════════════════════════════════════════════════════════════
# EXÉCUTION DES TRADES
# ═══════════════════════════════════════════════════════════════

def prepare_trade_request(symbol, signal):
    """
    Prépare la requête de trade (compatible multi-comptes)
    
    Returns:
        tuple: (request_dict, lot, entry_price, tp1, tp2, tp3)
    """
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        logging.error(f"Impossible de récupérer le tick pour {symbol}")
        return None, 0, 0, 0, 0, 0
    
    is_buy = signal['type'] == "BUY"
    entry_price = tick.ask if is_buy else tick.bid
    
    # Calcul du lot avec ajustement Squeeze
    base_lot = get_dynamic_lot(symbol, entry_price, signal['sl'], risk_percent=RISK_PER_TRADE)
    lot = base_lot * signal.get('size_multiplier', 1.0)
    
    # Arrondi au lot step
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info:
        lot_step = symbol_info.volume_step
        lot = round(lot / lot_step) * lot_step
        lot = max(symbol_info.volume_min, min(symbol_info.volume_max, lot))
    
    lot = float(lot)
    
    # TPs multiples (3 niveaux)
    tp_final = signal['tp']
    distance_tp = abs(tp_final - entry_price)
    
    tp1 = entry_price + (distance_tp * 0.33 * (1 if is_buy else -1))
    tp2 = entry_price + (distance_tp * 0.66 * (1 if is_buy else -1))
    tp3 = tp_final
    
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": entry_price,
        "sl": float(signal['sl']),
        "tp": float(signal['tp']),
        "magic": MAGIC_NUMBER,
        "comment": f"STRUCTURE_{symbol[:3]}",
        "type_filling": mt5.ORDER_FILLING_FOK,
        "type_time": mt5.ORDER_TIME_GTC,
    }
    
    return request, lot, entry_price, tp1, tp2, tp3


def open_trade(symbol, signal):
    """
    Exécute un trade avec la nouvelle stratégie
    
    Returns:
        tuple: (ticket, lot)
    """
    request, lot, entry_price, tp1, tp2, tp3 = prepare_trade_request(symbol, signal)
    if request is None:
        return None, 0
    
    result = mt5.order_send(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        account = mt5.account_info()
        balance = float(account.balance) if account else 0.0
        
        distance_sl = abs(entry_price - signal['sl'])
        distance_tp = abs(signal['tp'] - entry_price)
        rr = round(distance_tp / distance_sl, 2) if distance_sl > 0 else 0
        
        is_buy = signal['type'] == "BUY"
        squeeze_tag = "🔥 SQUEEZE" if signal.get('is_squeeze') else ""
        
        msg = (
            f"🔔 <b>NOUVELLE POSITION</b> {squeeze_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Marché : <b>{symbol}</b>\n"
            f"Direction : {'🔵 BUY' if is_buy else '🔴 SELL'}\n"
            f"Lot : {lot:.3f} (Multiplier: {signal.get('size_multiplier', 1.0)}x)\n"
            f"Prix entrée : {entry_price:.5f}\n"
            f"SL : {signal['sl']:.5f}\n"
            f"TP1 (33%) : {tp1:.5f}\n"
            f"TP2 (66%) : {tp2:.5f}\n"
            f"TP FINAL : {tp3:.5f}\n"
            f"Risque : {RISK_PER_TRADE * 100:.1f}%\n"
            f"Ratio R:R : {rr}R\n"
            f"Solde : {balance:.2f} USD\n"
            f"Raison : {signal['reason']}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_alert(msg)
        
        save_open(ACCOUNT_NUMBER, symbol, result.order, signal['type'], entry_price)
        logging.info(f"✅ Trade ouvert | Ticket: {result.order} | {symbol} | {signal['type']} | Prix {entry_price:.5f}")
        
        return result.order, lot
    
    logging.error(f"❌ Échec {symbol}: {result.comment}")
    return None, 0


# ═══════════════════════════════════════════════════════════════
# CHANDELIER EXIT (Trailing Stop Dynamique)
# ═══════════════════════════════════════════════════════════════

def update_chandelier_exit(symbol, ticket, lot, signal, account_number=None):
    """
    Mise à jour du Chandelier Exit (Trailing Stop basé sur ATR)
    
    Règle :
    - Pour un BUY : SL = Plus Haut atteint - (3 x ATR)
    - Pour un SELL : SL = Plus Bas atteint + (3 x ATR)
    - Le SL ne redescend JAMAIS (BUY) ou ne remonte JAMAIS (SELL)
    """
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return False
    
    position = pos[0]
    is_buy = (position.type == mt5.ORDER_TYPE_BUY)
    current_sl = position.sl
    current_tp = position.tp
    
    # Récupération des données M1 pour ATR
    df_m1 = get_price_data(symbol, TIMEFRAME_M1, 50)
    if df_m1.empty:
        return False
    
    atr = calculate_atr(df_m1, ATR_PERIOD)
    if atr is None or atr.empty:
        return False
    
    current_atr = atr.iloc[-1]
    
    # Prix actuel
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False
    
    current_price = tick.bid if is_buy else tick.ask
    
    # Calcul du nouveau SL Chandelier
    if is_buy:
        # Pour un BUY : SL = Prix actuel - (3 x ATR)
        new_sl = current_price - (ATR_MULTIPLIER * current_atr)
        
        # Le SL ne peut que monter
        if new_sl > current_sl:
            modify_sl_tp(symbol, ticket, new_sl, current_tp)
            logging.info(f"📈 Chandelier Exit BUY | {symbol} Ticket {ticket} | SL: {current_sl:.5f} → {new_sl:.5f}")
            return True
    
    else:  # SELL
        # Pour un SELL : SL = Prix actuel + (3 x ATR)
        new_sl = current_price + (ATR_MULTIPLIER * current_atr)
        
        # Le SL ne peut que descendre
        if new_sl < current_sl or current_sl == 0:
            modify_sl_tp(symbol, ticket, new_sl, current_tp)
            logging.info(f"📉 Chandelier Exit SELL | {symbol} Ticket {ticket} | SL: {current_sl:.5f} → {new_sl:.5f}")
            return True
    
    return False


def modify_sl_tp(symbol, ticket, new_sl, new_tp):
    """Modifie le SL et TP d'une position"""
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": ticket,
        "sl": float(new_sl),
        "tp": float(new_tp),
        "magic": MAGIC_NUMBER,
    }
    
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"Échec modification SL/TP : {result.comment}")
        return False
    
    return True


def monitor_active_trade(symbol, ticket, lot, signal, account_number=None):
    """
    Surveillance active du trade avec Chandelier Exit
    
    Args:
        symbol: Symbole tradé
        ticket: Numéro du ticket
        lot: Volume du trade
        signal: Dictionnaire du signal (contient tp1, tp2, tp3)
        account_number: Numéro de compte (pour multi-comptes)
    """
    logging.info(f"👁️ Surveillance démarrée | {symbol} Ticket {ticket}")
    
    highest_reached = 0
    lowest_reached = float('inf')
    
    acc_num = account_number if account_number is not None else ACCOUNT_NUMBER
    
    while True:
        time.sleep(5)  # Vérification toutes les 5 secondes
        
        # Vérifier si la position existe encore
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            logging.info(f"🏁 Position {ticket} fermée | {symbol}")
            
            # Enregistrement en DB
            time.sleep(1)
            history = mt5.history_deals_get(ticket=ticket)
            if history:
                total_profit = sum(deal.profit for deal in history)
                last_price = history[-1].price
                save_close(acc_num, symbol, ticket, total_profit, last_price, status="CLOSED")
                
                # Message Telegram
                status_emoji = "✅" if total_profit > 0 else "❌"
                msg = (
                    f"🏁 <b>POSITION FERMÉE</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 Statut : {status_emoji}\n"
                    f"📈 Marché : <b>{symbol}</b>\n"
                    f"🎫 Ticket : {ticket}\n"
                    f"💰 P&L : {total_profit:+.2f} USD\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                send_telegram_alert(msg)
            
            break
        
        position = pos[0]
        current_profit = position.profit
        
        # Mise à jour du Chandelier Exit
        update_chandelier_exit(symbol, ticket, lot, signal, acc_num)
        
        # Tracking du plus haut/bas atteint (pour info)
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            if position.type == mt5.ORDER_TYPE_BUY:
                if tick.bid > highest_reached:
                    highest_reached = tick.bid
            else:
                if tick.ask < lowest_reached:
                    lowest_reached = tick.ask


# ═══════════════════════════════════════════════════════════════
# FILTRE DE VOLATILITÉ (Check si l'indice est assez actif)
# ═══════════════════════════════════════════════════════════════

def is_volatility_good(symbol):
    """
    Vérifie si l'indice est assez volatil pour être tradé
    
    Returns:
        tuple: (bool, str) - (OK ou pas, Raison)
    """
    df = get_price_data(symbol, mt5.TIMEFRAME_H1, 50)
    if df.empty:
        return False, "Pas de données"
    
    atr = calculate_atr(df, 14)
    if atr is None or len(atr) < 1:
        return False, "ATR Error"
    
    current_atr = atr.iloc[-1]
    avg_atr = atr.mean()
    
    if current_atr < (avg_atr * 0.7):
        return False, f"{symbol} trop calme (ATR faible)"
    
    return True, "OK"
