"""
STRATÉGIE DE TRADING — EMA 20/50 MULTI-TIMEFRAME
==================================================
Analyse en cascade : M30 → M15 → M1 (exécution)
Tendance directrice : M30 (EMA 20/50)
Signal d'entrée    : croisement EMA20/50 sur M1 aligné avec M30 et M15
Risk Management    : 2% du capital | SL = 1.5×ATR | TP = SL×2 | Break-Even + Trailing ATR
Fix appliqué       : respect du stop_level MT5 (Invalid stops 10016)
"""

import time
import threading
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
# PARAMÈTRES
# ═══════════════════════════════════════════════════════════════

TF_M30 = mt5.TIMEFRAME_M30
TF_M15 = mt5.TIMEFRAME_M15
TF_M1  = mt5.TIMEFRAME_M1

TF_LABELS = {
    TF_M30: "M30",
    TF_M15: "M15",
    TF_M1:  "M1",
}

TF_BARS = {
    TF_M30: 200,
    TF_M15: 200,
    TF_M1:  150,
}

EMA_FAST       = 20
EMA_SLOW       = 50
ATR_PERIOD     = 14
ATR_SL_MULT    = 1.5
ATR_TRAIL_MULT = 1.0
RR_RATIO       = 2.0
RISK_PER_TRADE = 0.02
BREAKEVEN_R    = 1.0

# Mutex global MT5 — partagé avec main.py et multi_account.py
_mt5_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════
# LOGGING HELPER
# ═══════════════════════════════════════════════════════════════

def log_step(symbol: str, step: str, message: str, level: str = "info"):
    """
    Affiche chaque étape d'analyse clairement dans la console.
    Format : [SYMBOLE           ] [ÉTAPE   ] message
    """
    tag  = f"[{symbol[:20]:<20}] [{step:<8}]"
    full = f"{tag} {message}"
    getattr(logging, level if level in ("debug", "warning", "error") else "info")(full)


# ═══════════════════════════════════════════════════════════════
# DONNÉES PRIX
# ═══════════════════════════════════════════════════════════════

def get_price_data(symbol: str, timeframe: int, bars: int = 200) -> pd.DataFrame:
    """Récupère les données OHLCV."""
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df
    except Exception as e:
        logging.error(f"get_price_data [{symbol}] tf={timeframe} : {e}")
        return pd.DataFrame()


def get_current_tick(symbol: str):
    """Retourne le tick courant ou None."""
    try:
        return mt5.symbol_info_tick(symbol)
    except Exception as e:
        logging.error(f"get_current_tick [{symbol}] : {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# INDICATEURS
# ═══════════════════════════════════════════════════════════════

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    result = ta.ema(series, length=period)
    return result if result is not None else pd.Series(dtype=float)


def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    result = ta.atr(df['high'], df['low'], df['close'], length=period)
    return result if result is not None else pd.Series(dtype=float)


# ═══════════════════════════════════════════════════════════════
# STOP LEVEL — Correction erreur MT5 10016 "Invalid stops"
# ═══════════════════════════════════════════════════════════════

def get_min_stop_distance(symbol: str) -> float:
    """
    Retourne la distance minimale autorisée pour le SL/TP en prix.
    MT5 définit stops_level en 'points' → conversion en prix.
    """
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.0
        return info.stops_level * info.point
    except Exception as e:
        logging.error(f"get_min_stop_distance [{symbol}] : {e}")
        return 0.0


def enforce_min_stop(symbol: str, entry: float, sl: float, tp: float,
                     is_buy: bool) -> tuple:
    """
    Ajuste SL et TP pour respecter la distance minimale MT5 (+ 20% de buffer).
    Returns: (sl_final, tp_final, sl_dist_finale)
    """
    min_dist      = get_min_stop_distance(symbol)
    min_dist_safe = min_dist * 1.2   # Buffer 20%

    sl_dist = abs(entry - sl)

    if sl_dist < min_dist_safe:
        log_step(symbol, "SL-ADJ",
                 f"⚠️ Distance SL={sl_dist:.5f} < min={min_dist_safe:.5f} → ajustement forcé",
                 level="warning")
        sl_dist = min_dist_safe
        sl = entry - sl_dist if is_buy else entry + sl_dist

    tp_dist = sl_dist * RR_RATIO
    tp = entry + tp_dist if is_buy else entry - tp_dist

    return sl, tp, sl_dist


# ═══════════════════════════════════════════════════════════════
# SIZING DYNAMIQUE (2% du capital)
# ═══════════════════════════════════════════════════════════════

def get_dynamic_lot(symbol: str, entry_price: float, sl_price: float,
                    risk_percent: float = RISK_PER_TRADE) -> float:
    """Calcule le volume pour risquer exactement risk_percent du capital."""
    try:
        account_info = mt5.account_info()
        if not account_info:
            return 0.01

        balance     = account_info.balance
        risk_amount = balance * risk_percent
        distance_sl = abs(entry_price - sl_price)

        if distance_sl == 0:
            return 0.01

        info = mt5.symbol_info(symbol)
        if not info:
            return 0.01

        distance_ticks = distance_sl / info.trade_tick_size
        cost_per_lot   = distance_ticks * info.trade_tick_value

        if cost_per_lot == 0:
            return info.volume_min

        lot = risk_amount / cost_per_lot
        lot = round(lot / info.volume_step) * info.volume_step
        lot = max(info.volume_min, min(info.volume_max, lot))

        log_step(symbol, "LOT",
                 f"Solde={balance:.2f} | Risque={risk_amount:.2f} | "
                 f"SL_dist={distance_sl:.5f} | Lot calculé={lot:.2f}")
        return float(lot)

    except Exception as e:
        logging.error(f"get_dynamic_lot [{symbol}] : {e}")
        return 0.01


# ═══════════════════════════════════════════════════════════════
# ANALYSE D'UN TIMEFRAME
# ═══════════════════════════════════════════════════════════════

def analyze_timeframe(symbol: str, timeframe: int) -> str:
    """
    Analyse la tendance sur un timeframe via EMA20/EMA50.
    Affiche le résultat dans la console.
    Returns: 'UP' | 'DOWN' | 'NEUTRAL'
    """
    tf_label = TF_LABELS.get(timeframe, str(timeframe))
    bars     = TF_BARS.get(timeframe, 200)

    df = get_price_data(symbol, timeframe, bars)
    if df.empty or len(df) < EMA_SLOW + 5:
        log_step(symbol, tf_label, "❌ Données insuffisantes pour ce TF", level="warning")
        return 'NEUTRAL'

    ema20 = calc_ema(df['close'], EMA_FAST)
    ema50 = calc_ema(df['close'], EMA_SLOW)

    if ema20.empty or ema50.empty:
        log_step(symbol, tf_label, "❌ Calcul EMA échoué", level="warning")
        return 'NEUTRAL'

    e20 = ema20.iloc[-1]
    e50 = ema50.iloc[-1]
    cl  = df['close'].iloc[-1]

    if pd.isna(e20) or pd.isna(e50):
        log_step(symbol, tf_label, "❌ Valeur EMA NaN", level="warning")
        return 'NEUTRAL'

    if cl > e50 and e20 > e50:
        trend, emoji = 'UP',      '📈'
    elif cl < e50 and e20 < e50:
        trend, emoji = 'DOWN',    '📉'
    else:
        trend, emoji = 'NEUTRAL', '➡️'

    log_step(symbol, tf_label,
             f"{emoji} Tendance={trend} | Prix={cl:.5f} | EMA20={e20:.5f} | EMA50={e50:.5f}")
    return trend


# ═══════════════════════════════════════════════════════════════
# SIGNAL M1 — CROISEMENT EMA20/50
# ═══════════════════════════════════════════════════════════════

def detect_ema_crossover_m1(symbol: str) -> dict | None:
    """
    Détecte un croisement EMA20/50 sur M1.
    Calcule SL (1.5×ATR) et TP (2×SL) en respectant le stop level MT5.
    """
    df = get_price_data(symbol, TF_M1, TF_BARS[TF_M1])

    if df.empty or len(df) < EMA_SLOW + 10:
        log_step(symbol, "M1-SIG", "❌ Données M1 insuffisantes", level="warning")
        return None

    ema20 = calc_ema(df['close'], EMA_FAST)
    ema50 = calc_ema(df['close'], EMA_SLOW)
    atr   = calc_atr(df, ATR_PERIOD)

    if ema20.empty or ema50.empty or atr.empty:
        log_step(symbol, "M1-SIG", "❌ Calcul indicateurs M1 échoué", level="warning")
        return None

    e20_cur  = ema20.iloc[-1]
    e20_prev = ema20.iloc[-2]
    e50_cur  = ema50.iloc[-1]
    e50_prev = ema50.iloc[-2]
    atr_val  = atr.iloc[-1]
    close    = df['close'].iloc[-1]

    if any(pd.isna(v) for v in [e20_cur, e20_prev, e50_cur, e50_prev, atr_val]):
        log_step(symbol, "M1-SIG", "❌ Valeurs NaN dans les indicateurs M1", level="warning")
        return None

    log_step(symbol, "M1-SIG",
             f"EMA20={e20_cur:.5f} EMA50={e50_cur:.5f} ATR={atr_val:.5f} | "
             f"Prev : EMA20={e20_prev:.5f} EMA50={e50_prev:.5f}")

    sl_dist_raw = ATR_SL_MULT * atr_val

    # ── CROISEMENT HAUSSIER ──
    if (e20_prev <= e50_prev) and (e20_cur > e50_cur):
        log_step(symbol, "M1-SIG", "🔀 Croisement HAUSSIER EMA20 > EMA50 détecté")
        sl_raw = close - sl_dist_raw
        tp_raw = close + sl_dist_raw * RR_RATIO
        sl, tp, sl_dist = enforce_min_stop(symbol, close, sl_raw, tp_raw, is_buy=True)
        return {
            'type':        'BUY',
            'entry_price': close,
            'sl':          sl,
            'tp':          tp,
            'atr':         atr_val,
            'sl_dist':     sl_dist,
            'reason':      f'EMA20_CROSS_UP_EMA50 | EMA20={e20_cur:.5f} EMA50={e50_cur:.5f}',
        }

    # ── CROISEMENT BAISSIER ──
    if (e20_prev >= e50_prev) and (e20_cur < e50_cur):
        log_step(symbol, "M1-SIG", "🔀 Croisement BAISSIER EMA20 < EMA50 détecté")
        sl_raw = close + sl_dist_raw
        tp_raw = close - sl_dist_raw * RR_RATIO
        sl, tp, sl_dist = enforce_min_stop(symbol, close, sl_raw, tp_raw, is_buy=False)
        return {
            'type':        'SELL',
            'entry_price': close,
            'sl':          sl,
            'tp':          tp,
            'atr':         atr_val,
            'sl_dist':     sl_dist,
            'reason':      f'EMA20_CROSS_DOWN_EMA50 | EMA20={e20_cur:.5f} EMA50={e50_cur:.5f}',
        }

    log_step(symbol, "M1-SIG", "— Aucun croisement sur cette bougie")
    return None


# ═══════════════════════════════════════════════════════════════
# ANALYSE MULTI-TIMEFRAME PRINCIPALE
# ═══════════════════════════════════════════════════════════════

def get_signal(symbol: str) -> dict | None:
    """
    Analyse complète M30 → M15 → M1.
    La tendance M30 est directrice ; M15 doit être aligné avant de chercher le signal M1.
    """
    logging.info("─" * 65)
    log_step(symbol, "ANALYSE", f"🔎 Début analyse multi-timeframe (M30 → M15 → M1)")

    # ÉTAPE 1 — Tendance M30 (directrice)
    trend_m30 = analyze_timeframe(symbol, TF_M30)
    if trend_m30 == 'NEUTRAL':
        log_step(symbol, "ANALYSE",
                 "⛔ Tendance M30 neutre → analyse arrêtée", level="warning")
        return None
    log_step(symbol, "ANALYSE",
             f"📌 Tendance directrice M30={trend_m30} → M15 et M1 doivent être alignés")

    # ÉTAPE 2 — Confirmation M15
    trend_m15 = analyze_timeframe(symbol, TF_M15)
    if trend_m15 != trend_m30:
        log_step(symbol, "ANALYSE",
                 f"⛔ M15={trend_m15} ≠ M30={trend_m30} → pas de trade", level="warning")
        return None
    log_step(symbol, "ANALYSE", f"✅ M15 aligné avec M30 ({trend_m15})")

    log_step(symbol, "ANALYSE",
             f"🟢 M30 + M15 ALIGNÉS ({trend_m30}) → recherche signal M1")

    # ÉTAPE 3 — Signal M1
    signal = detect_ema_crossover_m1(symbol)

    if signal is None:
        log_step(symbol, "ANALYSE", "— Pas de signal M1 pour l'instant")
        return None

    if (trend_m30 == 'UP' and signal['type'] != 'BUY') or \
       (trend_m30 == 'DOWN' and signal['type'] != 'SELL'):
        log_step(symbol, "ANALYSE",
                 f"⛔ Signal M1={signal['type']} opposé à M30={trend_m30} → ignoré",
                 level="warning")
        return None

    log_step(symbol, "SIGNAL",
             f"🎯 SIGNAL VALIDÉ : {signal['type']} | "
             f"Entry={signal['entry_price']:.5f} SL={signal['sl']:.5f} TP={signal['tp']:.5f}")
    return signal


# ═══════════════════════════════════════════════════════════════
# FILTRE VOLATILITÉ
# ═══════════════════════════════════════════════════════════════

def is_volatility_good(symbol: str) -> tuple:
    """Vérifie si l'ATR M30 est > 70% de sa moyenne → marché actif."""
    log_step(symbol, "VOL", "Vérification volatilité (ATR M30)...")
    df = get_price_data(symbol, TF_M30, 50)
    if df.empty:
        log_step(symbol, "VOL", "❌ Pas de données M30", level="warning")
        return False, "Pas de données M30"

    atr = calc_atr(df, ATR_PERIOD)
    if atr.empty or len(atr.dropna()) < 5:
        log_step(symbol, "VOL", "❌ ATR insuffisant", level="warning")
        return False, "ATR insuffisant"

    current_atr = atr.iloc[-1]
    avg_atr     = atr.dropna().mean()

    if current_atr < avg_atr * 0.70:
        msg = f"⚠️ Marché calme : ATR={current_atr:.5f} < 70% moy={avg_atr:.5f}"
        log_step(symbol, "VOL", msg, level="warning")
        return False, msg

    log_step(symbol, "VOL",
             f"✅ Volatilité OK : ATR={current_atr:.5f} / moy={avg_atr:.5f}")
    return True, "OK"


# ═══════════════════════════════════════════════════════════════
# PRÉPARATION ET EXÉCUTION DES TRADES
# ═══════════════════════════════════════════════════════════════

def prepare_trade_request(symbol: str, signal: dict) -> tuple:
    """
    Prépare la requête MT5 avec SL/TP validés.
    Returns: (request_dict, lot, entry_price) ou (None, 0, 0)
    """
    tick = get_current_tick(symbol)
    if not tick:
        log_step(symbol, "EXEC", "❌ Tick indisponible", level="error")
        return None, 0, 0

    is_buy      = signal['type'] == 'BUY'
    entry_price = tick.ask if is_buy else tick.bid

    # Recalcul avec prix d'exécution réel + validation stop level
    sl_dist      = signal['sl_dist']
    sl_raw       = entry_price - sl_dist if is_buy else entry_price + sl_dist
    tp_raw       = entry_price + sl_dist * RR_RATIO if is_buy else entry_price - sl_dist * RR_RATIO
    sl, tp, sl_dist_final = enforce_min_stop(symbol, entry_price, sl_raw, tp_raw, is_buy)

    lot = get_dynamic_lot(symbol, entry_price, sl, RISK_PER_TRADE)

    log_step(symbol, "EXEC",
             f"Ordre préparé | {signal['type']} @ {entry_price:.5f} | "
             f"SL={sl:.5f} TP={tp:.5f} | Lot={lot:.2f}")

    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         order_type,
        "price":        entry_price,
        "sl":           float(sl),
        "tp":           float(tp),
        "magic":        MAGIC_NUMBER,
        "comment":      f"EMA_{signal['type'][:1]}_{symbol[:4]}",
        "type_filling": mt5.ORDER_FILLING_FOK,
        "type_time":    mt5.ORDER_TIME_GTC,
    }

    signal['_exec_entry'] = entry_price
    signal['_exec_sl']    = sl
    signal['_exec_tp']    = tp
    signal['_exec_lot']   = lot
    signal['sl_dist']     = sl_dist_final

    return request, lot, entry_price


def open_trade(symbol: str, signal: dict) -> tuple:
    """Exécute un trade (single-account). Returns: (ticket, lot)."""
    request, lot, entry_price = prepare_trade_request(symbol, signal)
    if request is None:
        return None, 0

    log_step(symbol, "EXEC", "📤 Envoi ordre MT5...")

    with _mt5_lock:
        result = mt5.order_send(request)

    if result is None:
        log_step(symbol, "EXEC", "❌ order_send a retourné None", level="error")
        return None, 0

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        sl_price = request['sl']
        tp_price = request['tp']
        rr = round(abs(tp_price - entry_price) / abs(sl_price - entry_price), 2) \
             if abs(sl_price - entry_price) > 0 else 0

        account = mt5.account_info()
        balance = float(account.balance) if account else 0.0

        log_step(symbol, "EXEC",
                 f"✅ TRADE OUVERT | Ticket={result.order} | {signal['type']} @ {entry_price:.5f} "
                 f"| SL={sl_price:.5f} TP={tp_price:.5f} | Lot={lot:.2f} | R:R=1:{rr}")

        msg = (
            f"🔔 <b>NOUVELLE POSITION</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Marché   : <b>{symbol}</b>\n"
            f"Direction   : {'🔵 BUY' if signal['type'] == 'BUY' else '🔴 SELL'}\n"
            f"Lot         : {lot:.2f}\n"
            f"Entrée      : {entry_price:.5f}\n"
            f"Stop Loss   : {sl_price:.5f}\n"
            f"Take Profit : {tp_price:.5f}\n"
            f"Ratio R:R   : 1:{rr}\n"
            f"Risque      : {RISK_PER_TRADE * 100:.0f}%\n"
            f"Solde       : {balance:.2f} USD\n"
            f"Signal      : {signal['reason']}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_alert(msg)
        save_open(ACCOUNT_NUMBER, symbol, result.order, signal['type'], entry_price)
        return result.order, lot

    log_step(symbol, "EXEC",
             f"❌ ÉCHEC ORDRE | {result.comment} (code {result.retcode})", level="error")
    return None, 0


# ═══════════════════════════════════════════════════════════════
# MODIFICATION SL/TP
# ═══════════════════════════════════════════════════════════════

def modify_sl_tp(symbol: str, ticket: int, new_sl: float, new_tp: float) -> bool:
    """Modifie SL et TP d'une position ouverte."""
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   symbol,
        "position": ticket,
        "sl":       float(new_sl),
        "tp":       float(new_tp),
        "magic":    MAGIC_NUMBER,
    }
    with _mt5_lock:
        result = mt5.order_send(request)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        comment = result.comment if result else "None"
        log_step(symbol, "TRAIL",
                 f"❌ Échec modify SL/TP #{ticket} : {comment}", level="error")
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# SURVEILLANCE — Break-Even + Trailing Stop
# ═══════════════════════════════════════════════════════════════

def monitor_active_trade(symbol: str, ticket: int, lot: float,
                          signal: dict, account_number: int = None):
    """Surveillance active avec break-even et trailing stop basé sur ATR."""
    acc_num      = account_number if account_number is not None else ACCOUNT_NUMBER
    entry_price  = signal.get('_exec_entry', signal['entry_price'])
    sl_dist      = signal['sl_dist']
    risk_amount  = sl_dist * lot
    is_buy       = signal['type'] == 'BUY'
    breakeven_ok = False
    best_price   = entry_price

    log_step(symbol, "WATCH",
             f"👁️ Surveillance | Ticket={ticket} | {signal['type']} @ {entry_price:.5f} "
             f"| Lot={lot:.2f} | Risk≈{risk_amount:.2f}")

    while True:
        time.sleep(5)

        with _mt5_lock:
            pos_list = mt5.positions_get(ticket=ticket)

        if not pos_list:
            log_step(symbol, "WATCH", f"🏁 Position #{ticket} fermée")
            _record_trade_close(acc_num, symbol, ticket)
            break

        position   = pos_list[0]
        current_sl = position.sl
        current_tp = position.tp
        profit_usd = position.profit

        tick = get_current_tick(symbol)
        if not tick:
            continue

        current_price = tick.bid if is_buy else tick.ask

        df_m1   = get_price_data(symbol, TF_M1, 50)
        atr_now = calc_atr(df_m1, ATR_PERIOD)
        if atr_now.empty or pd.isna(atr_now.iloc[-1]):
            continue
        atr_val = atr_now.iloc[-1]

        new_sl  = current_sl
        updated = False

        if is_buy:
            if current_price > best_price:
                best_price = current_price

            if not breakeven_ok and profit_usd >= risk_amount * BREAKEVEN_R:
                new_sl       = entry_price + (atr_val * 0.1)
                breakeven_ok = True
                log_step(symbol, "BE",
                         f"🔒 BREAK-EVEN activé #{ticket} | SL → {new_sl:.5f} | "
                         f"P&L flottant={profit_usd:+.2f}")

            trailing_sl = best_price - (ATR_TRAIL_MULT * atr_val)
            if trailing_sl > new_sl:
                new_sl  = trailing_sl
                updated = True

        else:
            if current_price < best_price or best_price == entry_price:
                best_price = current_price

            if not breakeven_ok and profit_usd >= risk_amount * BREAKEVEN_R:
                new_sl       = entry_price - (atr_val * 0.1)
                breakeven_ok = True
                log_step(symbol, "BE",
                         f"🔒 BREAK-EVEN activé #{ticket} | SL → {new_sl:.5f} | "
                         f"P&L flottant={profit_usd:+.2f}")

            trailing_sl = best_price + (ATR_TRAIL_MULT * atr_val)
            if current_sl == 0 or trailing_sl < new_sl:
                new_sl  = trailing_sl
                updated = True

        if new_sl != current_sl and (updated or (breakeven_ok and new_sl != current_sl)):
            if modify_sl_tp(symbol, ticket, new_sl, current_tp):
                log_step(symbol, "TRAIL",
                         f"{'📈' if is_buy else '📉'} SL mis à jour #{ticket} | "
                         f"{current_sl:.5f} → {new_sl:.5f} | "
                         f"Best={best_price:.5f} | P&L={profit_usd:+.2f}")


def _record_trade_close(account_number: int, symbol: str, ticket: int):
    """Récupère le profit réel depuis MT5 et sauvegarde en base."""
    time.sleep(1)
    try:
        with _mt5_lock:
            history = mt5.history_deals_get(position=ticket)

        if not history:
            log_step(symbol, "DB",
                     f"⚠️ Aucun historique deal pour #{ticket}", level="warning")
            return

        total_profit = sum(d.profit + d.commission + d.swap for d in history)
        exit_deals   = [d for d in history if d.entry == mt5.DEAL_ENTRY_OUT]
        close_price  = exit_deals[-1].price if exit_deals else history[-1].price

        save_close(account_number, symbol, ticket, round(total_profit, 2), close_price, "CLOSED")

        status_emoji = "✅" if total_profit > 0 else "❌"
        log_step(symbol, "DB",
                 f"{status_emoji} Enregistré #{ticket} | Profit={total_profit:+.2f} USD "
                 f"| Close @ {close_price:.5f}")

        msg = (
            f"🏁 <b>POSITION FERMÉE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Statut  : {status_emoji}\n"
            f"Marché  : <b>{symbol}</b>\n"
            f"Ticket  : {ticket}\n"
            f"💰 P&L  : {total_profit:+.2f} USD\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_alert(msg)

    except Exception as e:
        log_step(symbol, "DB",
                 f"❌ Erreur enregistrement #{ticket} : {e}", level="error")
