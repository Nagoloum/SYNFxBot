# position_manager.py - VERSION CORRIGÉE ET AMÉLIORÉE
import MetaTrader5 as mt5
import logging
import pandas as pd
from datetime import datetime
from config import (
    SYMBOL, TRAILING_MULTIPLIER, ATR_PERIOD, TIMEFRAME,
    BREAKEVEN_MULTIPLIER, PARTIAL_CLOSE_PERCENT
)
from strategy import calculate_atr, is_reversal_signal
from utils import send_telegram_alert  # Pour alertes Telegram

def manage_positions():
    """Gère les positions ouvertes : trailing stop, breakeven, partial close, reversal"""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return  # Aucune position ouverte

    # Récupérer données historiques pour ATR et reversal
    timeframe_mt5 = getattr(mt5, f"TIMEFRAME_{TIMEFRAME}")
    rates = mt5.copy_rates_from_pos(SYMBOL, timeframe_mt5, 0, max(ATR_PERIOD + 10, 300))
    if rates is None or len(rates) < ATR_PERIOD + 1:
        logging.warning("Pas assez de données pour gestion positions")
        return

    df = pd.DataFrame(rates)
    atr = calculate_atr(df, ATR_PERIOD).iloc[-1]

    if pd.isna(atr) or atr <= 0:
        logging.error("ATR invalide – Skip gestion positions")
        return

    trailing_distance = atr * TRAILING_MULTIPLIER

    for pos in positions:
        profit = pos.profit
        ticket = pos.ticket
        pos_type = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"

        # 1. Vérifier reversal EMA → fermeture immédiate
        if is_reversal_signal(df, pos.type):
            logging.info(f"Reversal détecté → Fermeture position #{ticket}")
            close_position(pos)
            send_telegram_alert(f"⚠️ Reversal détecté → Position #{ticket} fermée ({pos_type})")
            continue

        # 2. Breakeven + Partial Close (quand profit ≥ risque initial)
        risk_distance = abs(pos.price_open - pos.sl) if pos.sl != 0 else atr
        if profit >= risk_distance * BREAKEVEN_MULTIPLIER and pos.sl != pos.price_open:
            # Partial close 50%
            partial_volume = round(pos.volume * PARTIAL_CLOSE_PERCENT, 2)
            if partial_volume >= 0.01:
                partial_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": SYMBOL,
                    "volume": partial_volume,
                    "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                    "position": ticket,
                    "price": mt5.symbol_info_tick(SYMBOL).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(SYMBOL).ask,
                    "deviation": 20,
                    "magic": pos.magic,
                    "comment": "Partial close breakeven",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                }
                result_partial = mt5.order_send(partial_request)
                if result_partial.retcode == mt5.TRADE_RETCODE_DONE:
                    logging.info(f"Partial close {partial_volume} lots sur #{ticket}")
                    send_telegram_alert(f"📉 Partial close {partial_volume} lots #{ticket} (breakeven)")

            # Breakeven SL
            new_sl = pos.price_open  # Exactement au prix d'entrée
            modify_breakeven = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": SYMBOL,
                "position": ticket,
                "sl": new_sl,
                "tp": pos.tp,
            }
            result_be = mt5.order_send(modify_breakeven)
            if result_be.retcode == mt5.TRADE_RETCODE_DONE:
                logging.info(f"Breakeven activé pour #{ticket} (SL à {new_sl:.2f})")
            else:
                logging.error(f"Échec breakeven #{ticket} : {result_be.comment}")

        # 3. Trailing Stop (seulement si profit > ATR)
        if profit > atr:
            new_sl = pos.price_open + trailing_distance if pos.type == mt5.ORDER_TYPE_BUY else pos.price_open - trailing_distance

            # Appliquer seulement si amélioration
            if (pos.type == mt5.ORDER_TYPE_BUY and new_sl > pos.sl) or \
               (pos.type == mt5.ORDER_TYPE_SELL and new_sl < pos.sl):
                modify_trailing = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": SYMBOL,
                    "position": ticket,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                result_trailing = mt5.order_send(modify_trailing)
                if result_trailing.retcode == mt5.TRADE_RETCODE_DONE:
                    logging.info(f"Trailing SL mis à jour #{ticket} → {new_sl:.2f} (profit {profit:.2f} USD)")
                    send_telegram_alert(f"📈 Trailing SL #{ticket} → {new_sl:.2f}")
                else:
                    logging.error(f"Échec trailing SL #{ticket} : {result_trailing.comment}")

def close_position(pos):
    """Ferme complètement une position"""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logging.error(f"Pas de tick pour fermer #{pos.ticket}")
        return

    close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

    close_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": pos.volume,
        "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "position": pos.ticket,
        "price": close_price,
        "deviation": 20,
        "magic": pos.magic,
        "comment": "Fermeture trailing/reversal",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    result = mt5.order_send(close_request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"Position #{pos.ticket} fermée à profit {pos.profit:.2f} USD")
        send_telegram_alert(f"❌ Position #{pos.ticket} fermée\nProfit : {pos.profit:.2f} USD")
    else:
        logging.error(f"Échec fermeture #{pos.ticket} : {result.comment} (code {result.retcode})")