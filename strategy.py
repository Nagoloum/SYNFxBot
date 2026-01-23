# strategy.py - Nouvelle stratégie trend-following avec filtres
import MetaTrader5 as mt5
import pandas as pd
import logging

from config import (
    TIMEFRAME_H4, TIMEFRAME_H1, ATR_PERIOD, EMA_PERIOD, ATR_WINDOW_AVG,
    MIN_RR, SL_MULTIPLIER, TP_MULTIPLIER, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    PRESETS, EDGE_SCORE_MIN  # MODIF: Ajout EDGE_SCORE_MIN dans config (e.g., 0.6 pour seuil 60%)
)


def get_preset(symbol):
    """Retourne preset basé sur symbole"""
    if "25" in symbol or "50" in symbol:
        return PRESETS["tranquille"]
    else:
        return PRESETS["agressif"]


def calculate_atr(df, period):
    """Calcul ATR"""
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_rsi(df, period):
    """Calcul RSI"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def get_trend_bias(symbol):
    """Bias H4 : EMA50 + pente"""
    rates_h4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, EMA_PERIOD + 10)
    if rates_h4 is None or len(rates_h4) < EMA_PERIOD + 1:
        return "neutral"

    df_h4 = pd.DataFrame(rates_h4)
    ema = df_h4['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    atr_h4 = calculate_atr(df_h4, ATR_PERIOD).iloc[-1]

    current_price = df_h4['close'].iloc[-1]
    ema_current = ema.iloc[-1]
    ema_prev = ema.iloc[-2]
    pente_positive = ema_current > ema_prev

    if current_price > ema_current + atr_h4:
        return "neutral"  # Oscillation
    if current_price > ema_current and pente_positive:
        return "bullish"
    elif current_price < ema_current and not pente_positive:
        return "bearish"
    return "neutral"


def find_pullback_zone(df, bias):
    """Zone S/D simplifiée : dernier swing comme support/resistance"""
    df['swing_high'] = df['high'][(df['high'].shift(1) < df['high']) & (df['high'].shift(-1) < df['high'])]
    df['swing_low'] = df['low'][(df['low'].shift(1) > df['low']) & (df['low'].shift(-1) > df['low'])]

    if bias == "bullish":
        zone_low = df['swing_low'].dropna().iloc[-1] if not df['swing_low'].dropna().empty else None
        return zone_low, None  # Support pour pullback BUY
    elif bias == "bearish":
        zone_high = df['swing_high'].dropna().iloc[-1] if not df['swing_high'].dropna().empty else None
        return None, zone_high  # Resistance pour pullback SELL
    return None, None


def check_rejection_candle(df, bias, zone_low, zone_high):
    """Confirmation : bougie rejet (mèche + close dans sens bias) + pin bar/engulfing"""  # MODIF: Renforcement price action
    last_candle = df.iloc[-1]
    prev_candle = df.iloc[-2]

    # Base rejection
    rejection = False
    if bias == "bullish" and zone_low:
        if last_candle['low'] <= zone_low and last_candle['close'] > last_candle['open']:
            rejection = True
    elif bias == "bearish" and zone_high:
        if last_candle['high'] >= zone_high and last_candle['close'] < last_candle['open']:
            rejection = True

    if not rejection:
        return False

    # Ajout pattern price action: pin bar (mèche > 2/3 body) ou engulfing
    body = abs(last_candle['close'] - last_candle['open'])
    wick_lower = last_candle['open'] - last_candle['low'] if last_candle['close'] > last_candle['open'] else last_candle['close'] - last_candle['low']
    wick_upper = last_candle['high'] - last_candle['open'] if last_candle['close'] > last_candle['open'] else last_candle['high'] - last_candle['close']
    
    is_pin_bar = (wick_lower > 2 * body or wick_upper > 2 * body) and body > 0
    
    is_engulfing = (body > abs(prev_candle['close'] - prev_candle['open'])) and (
        (bias == "bullish" and last_candle['close'] > prev_candle['high'] and last_candle['open'] < prev_candle['low']) or
        (bias == "bearish" and last_candle['close'] < prev_candle['low'] and last_candle['open'] > prev_candle['high'])
    )
    
    return is_pin_bar or is_engulfing


def calculate_edge_score(df, atr, atr_avg, rsi, bias):  # MODIF: Nouveau pour edge
    """Score edge simple (0-1) basé sur stats rapides: volatilité stable + RSI extrême + trend strength"""
    vol_stable = 1 if atr_avg * 0.8 < atr < atr_avg * 1.2 else 0  # Volatilité dans bande moyenne
    rsi_edge = 1 if (bias == "bullish" and rsi < 40) or (bias == "bearish" and rsi > 60) else 0  # Oversold/overbought plus agressif
    trend_strength = (df['close'].iloc[-1] - df['close'].iloc[-10]) / atr if atr > 0 else 0  # Momentum récent > 1 ATR
    trend_edge = 1 if abs(trend_strength) > 1 else 0
    
    score = (vol_stable + rsi_edge + trend_edge) / 3
    logging.debug(f"Edge score: {score}")
    return score


def generate_signal(symbol):
    """Génère signal pour un symbole"""
    preset = get_preset(symbol)
    volatility_low = preset["VOLATILITY_LOW"]
    volatility_high = preset["VOLATILITY_HIGH"]

    bias = get_trend_bias(symbol)
    if bias == "neutral":
        logging.debug(f"{symbol} : Bias neutre → Skip")
        return None

    rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, ATR_WINDOW_AVG + 50)
    if rates_h1 is None or len(rates_h1) < ATR_WINDOW_AVG + 1:
        return None

    df_h1 = pd.DataFrame(rates_h1)
    atr = calculate_atr(df_h1, ATR_PERIOD).iloc[-1]
    atr_avg = calculate_atr(df_h1, ATR_PERIOD).mean()

    if atr < atr_avg * volatility_low or atr > atr_avg * volatility_high:
        logging.debug(f"{symbol} : Volatilité hors limites → Skip")
        return None

    zone_low, zone_high = find_pullback_zone(df_h1, bias)
    if not zone_low and not zone_high:
        return None

    if not check_rejection_candle(df_h1, bias, zone_low, zone_high):
        logging.debug(f"{symbol} : Pas de bougie rejet → Skip")
        return None

    rsi = calculate_rsi(df_h1, RSI_PERIOD).iloc[-1]
    if bias == "bullish" and rsi > RSI_OVERSOLD:
        signal = "BUY"
    elif bias == "bearish" and rsi < RSI_OVERBOUGHT:
        signal = "SELL"
    else:
        logging.debug(f"{symbol} : RSI non confirmant → Skip")
        return None

    # MODIF: Filtre edge
    edge_score = calculate_edge_score(df_h1, atr, atr_avg, rsi, bias)
    if edge_score < EDGE_SCORE_MIN:
        logging.debug(f"{symbol} : Edge score trop faible {edge_score} → Skip")
        return None

    current_price = df_h1['close'].iloc[-1]
    if signal == "BUY":
        sl = zone_low - atr * SL_MULTIPLIER if zone_low else current_price - atr * SL_MULTIPLIER
        tp = current_price + atr * TP_MULTIPLIER
    else:
        sl = zone_high + atr * SL_MULTIPLIER if zone_high else current_price + atr * SL_MULTIPLIER
        tp = current_price - atr * TP_MULTIPLIER

    rr = abs(current_price - tp) / abs(current_price - sl) if abs(current_price - sl) > 0 else 0
    if rr < MIN_RR:
        logging.debug(f"{symbol} : RR trop faible {rr} → Skip")
        return None

    logging.info(f"{symbol} : Signal {signal} validé RR {rr} Edge {edge_score}")
    return signal, sl, tp