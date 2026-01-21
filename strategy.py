# strategy.py - VERSION FINALE, COMPLÈTE ET CORRIGÉE
from urllib import response
import MetaTrader5 as mt5
import pandas as pd # pyright: ignore[reportMissingModuleSource]
import requests # pyright: ignore[reportMissingModuleSource]
import logging
from datetime import datetime, timedelta
from config import (
    SYMBOL, TIMEFRAME, TIMEFRAME_M15, ATR_PERIOD, BIAS_THRESHOLD,
    NEWSAPI_KEY, ALPHA_VANTAGE_KEY, FRED_API_KEY, FMP_API_KEY,
    HIGH_IMPACT_PAUSE_MINUTES, RANGE_THRESHOLD, FVG_THRESHOLD, VOLATILITY_MIN, RR_RATIO,
    MIN_RR, MIN_CONFIRMATIONS
)
from bs4 import BeautifulSoup # pyright: ignore[reportMissingImports]

# ========================
# Fonctions Indicateurs
# ========================

def calculate_atr(df, period):
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

# ========================
# Analyse Fondamentale Automatisée
# ========================

def get_news_bias():
    if not NEWSAPI_KEY:
        return 0

    url = f"https://newsapi.org/v2/everything?q=gold+price+XAUUSD&apiKey={NEWSAPI_KEY}"
    try:
        response = requests.get(url)
        data = response.json()['articles']
        positive = sum(1 for a in data if 'rally' in a['title'].lower())
        negative = sum(1 for a in data if 'drop' in a['title'].lower())
        return 2 if positive > negative else -2 if negative > positive else 0  # Poids 2
    except:
        return 0

def get_inflation_score():
    if not FRED_API_KEY:
        return 0

    url = f"https://api.stlouisfed.org/fred/series/observations?series_id=PCEPI&api_key={FRED_API_KEY}&file_type=json"
    try:
        response = requests.get(url)
        value = float(response.json()['observations'][-1]['value'])
        return 3 if value > 3 else -1 if value < 2 else 0  # Poids 3
    except:
        return 0

def get_usd_dxy_score():
    if not ALPHA_VANTAGE_KEY:
        return 0

    url = f"https://www.alphavantage.co/query?function=FX_DAILY&from_symbol=EUR&to_symbol=USD&apikey={ALPHA_VANTAGE_KEY}"
    try:
        response = requests.get(url)
        last = float(response.json()['Time Series FX (Daily)'][list(response.json()['Time Series FX (Daily)'].keys())[0]]['4. close'])
        prev = float(response.json()['Time Series FX (Daily)'][list(response.json()['Time Series FX (Daily)'].keys())[1]]['4. close'])
        return 2.5 if last < prev else -2.5 if last > prev else 0  # Poids 2.5
    except:
        return 0

def get_gdp_score():
    if not FRED_API_KEY:
        return 0

    url = f"https://api.stlouisfed.org/fred/series/observations?series_id=GDP&api_key={FRED_API_KEY}&file_type=json"
    try:
        value = float(response.json()['observations'][-1]['value'])
        return -2 if value > 2 else 2 if value < 0 else 0  # Poids 2
    except:
        return 0

def get_geopolitical_vix_score():
    if not FRED_API_KEY:
        return 0

    url = f"https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&api_key={FRED_API_KEY}&file_type=json"
    try:
        vix = float(response.json()['observations'][-1]['value'])
        return 1.5 if vix > 20 else 0  # Poids 1.5
    except:
        return 0

def get_supply_demand_score():
    url = "https://www.gold.org/goldhub/data/gold-demand-by-country"
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Ex. : Parse dernier demand value (ajustez selector)
        demand_text = soup.find('div', class_='demand-value').text.strip()
        demand = float(demand_text.replace(',', '')) if demand_text else 0
        return 1.5 if demand > 1000 else -1.5 if demand < 800 else 0  # Poids 1.5
    except:
        return 0

def get_cot_sentiment_score():
    if not FMP_API_KEY:
        return 0

    url = f"https://financialmodelingprep.com/api/v4/commitment_of_traders_report/{SYMBOL}?apikey={FMP_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()[-1]
        net = data['long_positions'] - data['short_positions']
        return 1.5 if net > 0 else -1.5  # Poids 1.5
    except:
        return 0

def get_oil_score():
    if not ALPHA_VANTAGE_KEY:
        return 0

    url = f"https://www.alphavantage.co/query?function=WTI&interval=daily&apikey={ALPHA_VANTAGE_KEY}"
    try:
        response = requests.get(url)
        last = float(response.json()['data'][0]['value'])
        prev = float(response.json()['data'][1]['value'])
        return 2 if last > prev else -2  # Poids 2
    except:
        return 0

def get_seasonality_score(current_month):
    return 1 if current_month in [12, 1, 2] else -1 if current_month in [6, 7, 8] else 0  # Poids 1

def get_fundamental_bias(current_time):
    """Bias combiné avec scores pondérés"""
    scores = 0.0  # Utiliser float pour éviter problèmes d'addition

    scores += get_news_bias()                  # Géopolitique inclus
    scores += get_inflation_score()
    scores += get_usd_dxy_score()
    scores += get_gdp_score()
    scores += get_geopolitical_vix_score()
    scores += get_supply_demand_score()
    scores += get_cot_sentiment_score()
    scores += get_oil_score()
    scores += get_seasonality_score(current_time.month)  # Seul endroit où on utilise current_time pour l'instant

    logging.info(f"Score fondamental total : {scores:.2f}")

    if scores > BIAS_THRESHOLD:
        return 'bullish'
    elif scores < -BIAS_THRESHOLD:
        return 'bearish'
    else:
        return 'neutral'  # Plus jamais 'pause' ici → géré séparément si besoin
    
# ========================
# New: Supply/Demand Detection Functions
# ========================

def find_swings(df, lookback=5):
    """Find swing highs and lows"""
    df['swing_high'] = df['high'][(df['high'].shift(1) < df['high']) & (df['high'].shift(-1) < df['high'])]
    df['swing_low'] = df['low'][(df['low'].shift(1) > df['low']) & (df['low'].shift(-1) > df['low'])]
    return df

def detect_accumulation(df: pd.DataFrame, atr: float, lookback: int = 30, threshold_multiplier: float = None) -> bool:
    """
    Détecte une phase d'accumulation/consolidation de manière robuste.
    """
    if len(df) < lookback:
        return False

    from config import RANGE_THRESHOLD
    multiplier = threshold_multiplier if threshold_multiplier is not None else RANGE_THRESHOLD

    recent_high = df['high'].iloc[-lookback:]
    recent_low = df['low'].iloc[-lookback:]

    # 1. Critère principal : amplitude du range faible
    total_range = recent_high.max() - recent_low.min()
    if total_range <= atr * multiplier:
        return True

    # 2. Critère bonus : prix oscille horizontalement (pente faible)
    mid_values = (recent_high + recent_low) / 2
    if len(mid_values) > 1:
        slope = (mid_values.iloc[-1] - mid_values.iloc[0]) / (len(mid_values) - 1)
        if abs(slope) < atr * 0.15:  # pente < 15% de l'ATR par bougie → très plat
            return True

    return False

def find_pivot_candle(df, direction):
    """Find last pivot candle in accumulation"""
    if direction == 'demand':
        pivot_idx = df['low'].iloc[-20:].idxmin()  # Lowest low in recent range
    else:  # supply
        pivot_idx = df['high'].iloc[-20:].idxmax()  # Highest high
    return df.loc[pivot_idx]

def refine_in_m30(pivot_time):
    """Affinage de la zone pivot sur M30 (H1 / 2)"""
    timeframe_m30 = getattr(mt5, f"TIMEFRAME_{TIMEFRAME_M15}")
    start = pivot_time - timedelta(hours=4)
    end = pivot_time + timedelta(hours=2)
    rates = mt5.copy_rates_range(SYMBOL, timeframe_m30, start, end)
    if rates is None or len(rates) == 0:
        return None

    df_m30 = pd.DataFrame(rates)
    atr_m30 = calculate_atr(df_m30, ATR_PERIOD).iloc[-1]

    # FVG plus strict pour meilleure précision
    if 'detect_fvg' in globals():
        fvg_size = check_fvg(df_m30, atr_m30)
        if fvg_size < atr_m30 * FVG_THRESHOLD * 1.1:
            return None

    zone_low = df_m30['low'].min() - atr_m30 * 0.05
    zone_high = df_m30['high'].max() + atr_m30 * 0.05
    return zone_low, zone_high

# ========================
# Confirmations (BOS, FVG, Liquidity, Imbalance, Swing non récupéré)
# ========================

def check_bos(df):
    """Break of Structure"""
    last_high = df['swing_high'].dropna().iloc[-1] if not df['swing_high'].dropna().empty else df['high'].max()
    last_low = df['swing_low'].dropna().iloc[-1] if not df['swing_low'].dropna().empty else df['low'].min()
    if df['close'].iloc[-1] > last_high:
        return True, 'bullish'  # BOS up
    elif df['close'].iloc[-1] < last_low:
        return True, 'bearish'  # BOS down
    return False, None

def check_fvg(df, atr):
    """Fair Value Gap / Imbalance"""
    for i in range(1, len(df)-1):
        gap = abs(df['open'].iloc[i+1] - df['close'].iloc[i-1])
        if gap > atr * FVG_THRESHOLD:
            return True
    return False

def check_liquidity_sweep(df):
    """Liquidity internal/external (wick sweeping highs/lows)"""
    recent_wick_low = df['low'].iloc[-1] < df['swing_low'].dropna().iloc[-2] if len(df['swing_low'].dropna()) > 1 else False
    recent_wick_high = df['high'].iloc[-1] > df['swing_high'].dropna().iloc[-2] if len(df['swing_high'].dropna()) > 1 else False
    return recent_wick_low or recent_wick_high  # Sweep detected

def check_swing_non_recupere(df, direction):
    """Swing low/high non récupéré"""
    if direction == 'demand':
        return df['low'].iloc[-1] > df['swing_low'].dropna().iloc[-2] if len(df['swing_low'].dropna()) > 1 else False
    else:
        return df['high'].iloc[-1] < df['swing_high'].dropna().iloc[-2] if len(df['swing_high'].dropna()) > 1 else False

    confirm_count = 0
    conf_details = []

    bos, bos_dir = check_bos(df)
    if bos and ((direction == 'demand' and bos_dir == 'bullish') or (direction == 'supply' and bos_dir == 'bearish')):
        confirm_count += 1
        conf_details.append('BOS')

    if check_fvg(df, atr):
        confirm_count += 1
        conf_details.append('FVG/Imbalance')

    if check_liquidity_sweep(df):
        confirm_count += 1
        conf_details.append('Liquidity Sweep')

    if check_swing_non_recupere(df, direction):
        confirm_count += 1
        conf_details.append('Swing Non Récupéré')

    return confirm_count, conf_details

# ========================
# Trend Bias from Higher TF (H4)
# ========================

def get_trend_bias():
    """Analyse de la tendance actuelle sur H4 (demande explicite)"""
    timeframe_h4 = mt5.TIMEFRAME_H4
    rates_h4 = mt5.copy_rates_from_pos(SYMBOL, timeframe_h4, 0, 100)
    if rates_h4 is None or len(rates_h4) < 50:
        logging.warning("Pas assez de données H4 pour trend bias")
        return 'neutral'

    df_h4 = pd.DataFrame(rates_h4)
    df_h4 = find_swings(df_h4)

    bos, bos_dir = check_bos(df_h4)
    if bos and bos_dir in ['bullish', 'bearish']:
        return bos_dir

    current_price = df_h4['close'].iloc[-1]
    last_high = df_h4['swing_high'].dropna().iloc[-1] if not df_h4['swing_high'].dropna().empty else current_price
    last_low = df_h4['swing_low'].dropna().iloc[-1] if not df_h4['swing_low'].dropna().empty else current_price

    if current_price > last_high:
        return 'bullish'
    elif current_price < last_low:
        return 'bearish'
    return 'neutral'
# ========================
# Signal Generation
# ========================

def get_confirmations(df, atr, direction):
    conf_count = 0
    details = []

    if 'detect_fvg' in globals() and check_fvg(df, atr):
        conf_count += 1
        details.append("FVG")

    bos, _ = check_bos(df)
    if bos:
        conf_count += 1
        details.append("BOS")

    # Bonus volume croissant en phase d'accumulation
    recent_vol = df['tick_volume'].tail(10)
    if len(recent_vol) >= 5 and recent_vol.is_monotonic_increasing:
        conf_count += 1
        details.append("volume_up")

    return conf_count, details

def generate_signal(current_time):
    current_hour_utc = current_time.hour
    if not (6 <= current_hour_utc <= 17):
        logging.info(f"Hors session active ({current_hour_utc}h UTC) → Skip")
        return None

    if not mt5.symbol_select(SYMBOL, True):
        return None

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None

    positions = mt5.positions_get(symbol=SYMBOL)
    if positions and len(positions) > 0:
        logging.info("Position déjà ouverte → Pas de nouvelle entrée")
        return None

    # Données H1
    timeframe_mt5 = getattr(mt5, f"TIMEFRAME_{TIMEFRAME}")
    rates = mt5.copy_rates_from_pos(SYMBOL, timeframe_mt5, 0, 300)
    if rates is None or len(rates) < ATR_PERIOD + 50:
        return None

    df = pd.DataFrame(rates)
    df = find_swings(df)
    atr = calculate_atr(df, ATR_PERIOD).iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None

    avg_atr = calculate_atr(df, ATR_PERIOD).mean()
    if atr < avg_atr * VOLATILITY_MIN:
        logging.info("Volatilité trop faible → Skip")
        return None

    # Tendance H4 (clé de l'optimisation)
    trend_bias = get_trend_bias()
    if trend_bias == 'neutral':
        logging.info("Trend H4 neutre → Skip")
        return None

    direction = 'demand' if trend_bias == 'bullish' else 'supply'

    if not detect_accumulation(df, atr):
        return None

    pivot_candle = find_pivot_candle(df, direction)
    if pivot_candle is None:
        return None

    pivot_time = datetime.fromtimestamp(pivot_candle['time'])
    refined_zone = refine_in_m30(pivot_time)
    if not refined_zone:
        return None
    zone_low, zone_high = refined_zone

    current_price = df['close'].iloc[-1]
    if not (zone_low <= current_price <= zone_high):
        logging.info("Prix hors zone affinée M30 → Skip")
        return None

    conf_count, conf_details = get_confirmations(df, atr, direction)
    if conf_count < MIN_CONFIRMATIONS:
        logging.info(f"Confirmations insuffisantes ({conf_count} < {MIN_CONFIRMATIONS}) → Skip")
        return None

    # Calcul SL/TP
    if direction == 'demand':
        sl = zone_low - (atr * 0.1)
        tp = df['swing_high'].dropna().iloc[-1] if not df['swing_high'].dropna().empty else current_price + (atr * RR_RATIO)
        signal = "BUY"
    else:
        sl = zone_high + (atr * 0.1)
        tp = df['swing_low'].dropna().iloc[-1] if not df['swing_low'].dropna().empty else current_price - (atr * RR_RATIO)
        signal = "SELL"

    risk = abs(current_price - sl)
    reward = abs(tp - current_price)
    rr = reward / risk if risk > 0 else 0
    if rr < MIN_RR:
        logging.info(f"RR trop faible ({rr:.2f} < {MIN_RR}) → Skip")
        return None

    logging.info(f"Signal validé: {signal} | RR: {rr:.2f} | Confirmations: {conf_count} ({conf_details})")
    return signal, sl, tp

def is_reversal_signal(df, position_type):
    bos, bos_dir = check_bos(df)
    if position_type == mt5.ORDER_TYPE_BUY and bos and bos_dir == 'bearish':
        return True
    if position_type == mt5.ORDER_TYPE_SELL and bos and bos_dir == 'bullish':
        return True
    return False