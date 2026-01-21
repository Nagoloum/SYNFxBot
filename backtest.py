# backtest.py - Version corrigée et complète pour backtest fonctionnel
import MetaTrader5 as mt5
import pandas as pd
import logging
from datetime import datetime
from config import (
    SYMBOL, ATR_PERIOD,
    RISK_PERCENT, RR_RATIO, TRAILING_MULTIPLIER,
    BREAKEVEN_MULTIPLIER, PARTIAL_CLOSE_PERCENT, MIN_RR, MIN_CONFIRMATIONS,
    RANGE_THRESHOLD, FVG_THRESHOLD, VOLATILITY_MIN
)
from strategy import (
    calculate_atr, is_reversal_signal, find_swings, detect_accumulation,
    find_pivot_candle, get_confirmations
)

# Configuration logging
logging.basicConfig(
    level=logging.INFO,  # Change en DEBUG si tu veux plus de détails
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def get_trend_bias(historical_df=None):
    if historical_df is not None:
        # Resample les données H1 en H4 pour le backtest
        df_h4 = historical_df.resample('4h').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'tick_volume': 'sum'
        }).dropna()
        if len(df_h4) < 50:
            return 'neutral'
        ema50 = df_h4['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        current_close = df_h4['close'].iloc[-1]
        if current_close > ema50:
            return 'bullish'
        elif current_close < ema50:
            return 'bearish'
        return 'neutral'

    # Version live originale (pour le bot réel)
    timeframe_h4 = mt5.TIMEFRAME_H4
    rates_h4 = mt5.copy_rates_from_pos(SYMBOL, timeframe_h4, 0, 100)
    if rates_h4 is None or len(rates_h4) < 50:
        return 'neutral'
    df_h4 = pd.DataFrame(rates_h4)
    ema50 = df_h4['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    if df_h4['close'].iloc[-1] > ema50:
        return 'bullish'
    elif df_h4['close'].iloc[-1] < ema50:
        return 'bearish'
    return 'neutral'
def backtest_xaufxbot(start_date: tuple, end_date: tuple, initial_balance: float = 10000.0):
    """Backtest complet de la stratégie S/D sur XAUUSD"""
    if not mt5.initialize():
        logging.error("Échec initialisation MT5")
        return

    from_date = datetime(*start_date)
    to_date = datetime(*end_date)

    logging.info("Récupération des données historiques H1...")
    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_H1, from_date, to_date)

    if rates is None or len(rates) == 0:
        logging.error("Aucune donnée historique récupérée")
        mt5.shutdown()
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time')

    logging.info(f"Backtest lancé : {len(df)} bougies H1 du {start_date} au {end_date}")
    logging.info(f"Balance initiale : {initial_balance:.2f} USD")

    # Variables de simulation
    balance = initial_balance
    equity = initial_balance
    max_equity = initial_balance
    max_drawdown = 0
    position = None  # None, 'BUY' ou 'SELL'
    entry_price = 0.0
    sl = 0.0
    tp = 0.0
    volume = 0.0
    trades = []
    wins = 0
    losses = 0

    # Boucle principale
    for i in range(ATR_PERIOD + 50, len(df)):
        current_time = df.index[i]
        current_hour = current_time.hour

        # Filtre horaire : session active 6h-17h UTC
        if not (6 <= current_hour <= 17):
            continue

        row = df.iloc[i]
        slice_df = df.iloc[:i + 1].copy()

        # Calcul ATR
        slice_df['atr'] = calculate_atr(slice_df, ATR_PERIOD)
        atr = slice_df['atr'].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            continue

        # Filtre volatilité minimale
        avg_atr = slice_df['atr'].mean()
        if atr < avg_atr * VOLATILITY_MIN:
            logging.debug(f"[{current_time}] Volatilité trop faible ({atr:.2f} < {avg_atr * VOLATILITY_MIN:.2f}) → Skip")
            continue

        # Détection des swings
        slice_df = find_swings(slice_df)

        # === Gestion d'une position ouverte ===
        if position:
            current_price = row['close']
            profit_pips = (current_price - entry_price) if position == 'BUY' else (entry_price - current_price)
            profit_usd = profit_pips * volume * 10  # XAUUSD : 1 lot = 10 USD par pip

            # Mise à jour equity et drawdown
            equity = balance + profit_usd
            max_equity = max(max_equity, equity)
            drawdown = max_equity - equity
            max_drawdown = max(max_drawdown, drawdown)

            # Breakeven + Partial Close
            risk_pips = abs(entry_price - sl)
            if profit_pips >= risk_pips * BREAKEVEN_MULTIPLIER and sl != entry_price:
                partial_profit = profit_usd * PARTIAL_CLOSE_PERCENT
                balance += partial_profit
                volume *= (1 - PARTIAL_CLOSE_PERCENT)
                sl = entry_price  # Breakeven
                logging.info(f"[{current_time}] Breakeven + Partial close 50% → Nouveau solde : {balance:.2f} USD")

            # Trailing Stop
            if profit_pips > atr:
                new_sl = entry_price + (atr * TRAILING_MULTIPLIER) if position == 'BUY' else entry_price - (atr * TRAILING_MULTIPLIER)
                if (position == 'BUY' and new_sl > sl) or (position == 'SELL' and new_sl < sl):
                    sl = new_sl
                    logging.info(f"[{current_time}] Trailing stop mis à jour → SL = {sl:.2f}")

            # Fermeture sur signal de reversal (BOS opposé)
            if is_reversal_signal(slice_df, mt5.ORDER_TYPE_BUY if position == 'BUY' else mt5.ORDER_TYPE_SELL):
                profit_usd = profit_pips * volume * 10
                result = 'win' if profit_usd > 0 else 'loss'
                if result == 'win':
                    wins += 1
                else:
                    losses += 1
                balance += profit_usd
                trades.append({
                    'close_date': current_time,
                    'type': position,
                    'entry': entry_price,
                    'exit': current_price,
                    'profit_usd': round(profit_usd, 2),
                    'result': result
                })
                logging.info(f"[{current_time}] Reversal → Position fermée ({result}) | Profit : {profit_usd:.2f} USD")
                position = None
                continue

            # SL ou TP touché (simulé)
            if (position == 'BUY' and current_price <= sl) or (position == 'SELL' and current_price >= sl):
                exit_price = sl
                profit_pips = (exit_price - entry_price) if position == 'BUY' else (entry_price - exit_price)
                profit_usd = profit_pips * volume * 10
                result = 'loss'
                losses += 1
                balance += profit_usd
                trades.append({'close_date': current_time, 'type': position, 'profit_usd': round(profit_usd, 2), 'result': result})
                logging.info(f"[{current_time}] Stop Loss touché → Perte : {profit_usd:.2f} USD")
                position = None
                continue

            if (position == 'BUY' and current_price >= tp) or (position == 'SELL' and current_price <= tp):
                exit_price = tp
                profit_pips = (exit_price - entry_price) if position == 'BUY' else (entry_price - exit_price)
                profit_usd = profit_pips * volume * 10
                result = 'win'
                wins += 1
                balance += profit_usd
                trades.append({'close_date': current_time, 'type': position, 'profit_usd': round(profit_usd, 2), 'result': result})
                logging.info(f"[{current_time}] Take Profit atteint → Gain : {profit_usd:.2f} USD")
                position = None
                continue

            # Continue si position toujours ouverte
            continue

        # === Recherche d'un nouveau signal (pas de position ouverte) ===
        if not position:
            # Trend bias basé sur données historiques
            trend_bias = get_trend_bias(historical_df=slice_df)
            direction = 'demand' if trend_bias == 'bullish' else 'supply' if trend_bias == 'bearish' else None

            if not direction:
                logging.debug(f"[{current_time}] Bias neutre → Pas de direction claire")
                continue

            if not detect_accumulation(slice_df, atr):
                logging.debug(f"[{current_time}] Pas de phase d'accumulation détectée")
                continue

            pivot_candle = find_pivot_candle(slice_df, direction)
            if pivot_candle is None:
                logging.debug(f"[{current_time}] Aucun pivot candle trouvé")
                continue

            # Zone simplifiée en H1 (pas de refine M15 en backtest)
            zone_low = pivot_candle['low'] - atr * 0.1   # plus large
            zone_high = pivot_candle['high'] + atr * 0.1

            current_price = row['close']
            if not (zone_low <= current_price <= zone_high):
                logging.debug(f"[{current_time}] Prix hors zone ({current_price:.2f} pas dans [{zone_low:.2f} - {zone_high:.2f}])")
                continue

            conf_count, conf_details = get_confirmations(slice_df, atr, direction)
            if conf_count < MIN_CONFIRMATIONS:
                logging.debug(f"[{current_time}] Confirmations insuffisantes ({conf_count} < {MIN_CONFIRMATIONS})")
                continue

            # Calcul SL/TP
            if direction == 'demand':
                sl = zone_low - (atr * 0.1)
                tp = slice_df['swing_high'].dropna().iloc[-1] if not slice_df['swing_high'].dropna().empty else current_price + (atr * RR_RATIO)
                signal = "BUY"
            else:
                sl = zone_high + (atr * 0.1)
                tp = slice_df['swing_low'].dropna().iloc[-1] if not slice_df['swing_low'].dropna().empty else current_price - (atr * RR_RATIO)
                signal = "SELL"

            risk = abs(current_price - sl)
            reward = abs(tp - current_price)
            rr = reward / risk if risk > 0 else 0
            if rr < MIN_RR:
                logging.debug(f"[{current_time}] RR trop faible ({rr:.2f} < {MIN_RR})")
                continue

            # Calcul du volume (risk 1% du solde)
            risk_amount = balance * RISK_PERCENT
            volume = risk_amount / (risk * 10)  # 10 USD par pip pour XAUUSD
            volume = max(round(volume, 2), 0.01)

            # Ouverture de la position
            position = signal
            entry_price = current_price
            trades.append({
                'open_date': current_time,
                'type': signal,
                'entry': entry_price,
                'sl': sl,
                'tp': tp,
                'volume': volume
            })
            logging.info(f"[{current_time}] NOUVELLE POSITION {signal} | "
                         f"Entry: {entry_price:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | "
                         f"RR: {rr:.2f} | Volume: {volume} lots | Confirmations: {conf_count}")

    # === Statistiques finales ===
    total_trades = len(trades) // 2 if trades else 0  # Chaque trade a open + close (approx)
    actual_trades = wins + losses
    win_rate = (wins / actual_trades * 100) if actual_trades > 0 else 0
    profit_total = balance - initial_balance
    profit_percent = (profit_total / initial_balance * 100) if initial_balance > 0 else 0

    logging.info("\n" + "="*50)
    logging.info("           RÉSULTATS DU BACKTEST")
    logging.info("="*50)
    logging.info(f"Période             : {start_date} → {end_date}")
    logging.info(f"Balance initiale    : {initial_balance:.2f} USD")
    logging.info(f"Balance finale      : {balance:.2f} USD")
    logging.info(f"Profit net          : {profit_total:+.2f} USD ({profit_percent:+.2f}%)")
    logging.info(f"Trades exécutés     : {actual_trades} (Wins: {wins} | Losses: {losses})")
    logging.info(f"Win rate            : {win_rate:.2f}%")
    logging.info(f"Max Drawdown        : {max_drawdown:.2f} USD")
    logging.info("="*50)

    mt5.shutdown()
    logging.info("Backtest terminé et connexion MT5 fermée.")


if __name__ == "__main__":
    # Exemple : toute l'année 2025
    backtest_xaufxbot((2025, 1, 1), (2025, 12, 31), initial_balance=1000)