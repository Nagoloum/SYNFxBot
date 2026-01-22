# position_manager.py - Gestion positions multi-symboles
import MetaTrader5 as mt5
import logging
import pandas as pd

from config import ATR_PERIOD, BREAKEVEN_MULTIPLIER, PARTIAL_CLOSE_PERCENT, DAILY_LOSS_LIMIT, SYMBOLS
from strategy import calculate_atr, get_preset
from utils import send_telegram_alert
from database import update_trade_on_close
from datetime import datetime, timezone, timedelta
import time


def check_loss_limits():
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc)

    history = mt5.history_deals_get(today_start, now)

    if history is None or not history:
        logging.debug("Aucun deal aujourd'hui ou erreur récupération")
        return True

    closed_profit = sum(deal.profit for deal in history if deal.entry == mt5.DEAL_ENTRY_OUT)

    balance = mt5.account_info().balance
    if balance <= 0:
        return True

    pct = closed_profit / balance

    if pct < DAILY_LOSS_LIMIT:
        logging.warning(f"Daily loss limit reached: {pct*100:.2f}% today")
        return False
    return True


def manage_positions():
    """Gère positions pour tous symboles"""
    if not check_loss_limits():
        return

    for symbol in SYMBOLS:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            continue

        rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, ATR_PERIOD + 10)
        if not rates_h1:
            continue

        df = pd.DataFrame(rates_h1)
        atr = calculate_atr(df, ATR_PERIOD).iloc[-1]
        if pd.isna(atr) or atr <= 0:
            continue

        preset = get_preset(symbol)
        trailing_multiplier = preset["TRAILING_MULTIPLIER"]

        for pos in positions:
            profit = pos.profit
            ticket = pos.ticket
            pos_type = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"

            risk_distance = abs(pos.price_open - pos.sl) if pos.sl != 0 else atr

            # Breakeven + Partial si profit >= risque
            if profit >= risk_distance * BREAKEVEN_MULTIPLIER and pos.sl != pos.price_open:
                # Partial close
                partial_volume = round(pos.volume * PARTIAL_CLOSE_PERCENT, 2)
                if partial_volume >= 0.01:
                    tick = mt5.symbol_info_tick(symbol)
                    price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                    partial_request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": partial_volume,
                        "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                        "position": ticket,
                        "price": price,
                        "deviation": 20,
                        "magic": pos.magic,
                        "comment": "Partial close",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_RETURN,
                    }
                    result_partial = mt5.order_send(partial_request)
                    if result_partial.retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(f"{symbol} : Partial close {partial_volume} sur {ticket}")

                # Breakeven SL
                new_sl = pos.price_open
                modify_request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": new_sl, "tp": pos.tp}
                result_be = mt5.order_send(modify_request)
                if result_be.retcode == mt5.TRADE_RETCODE_DONE:
                    logging.info(f"{symbol} : Breakeven sur {ticket}")

            # Trailing si profit > 1.5x ATR
            if profit > atr * 1.5:
                new_sl = pos.price_current - atr * trailing_multiplier if pos_type == "SELL" else pos.price_current + atr * trailing_multiplier
                if (pos_type == "BUY" and new_sl > pos.sl) or (pos_type == "SELL" and new_sl < pos.sl):
                    modify_request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": new_sl, "tp": pos.tp}
                    result_trailing = mt5.order_send(modify_request)
                    if result_trailing.retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(f"{symbol} : Trailing SL updated {ticket}")

            # Close si reversal ou manual (mais pas de reversal dans nouvelle strat)


def close_position(symbol, pos, reason="manual"):
    """Ferme position"""
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return

    close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": pos.volume,
        "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "position": pos.ticket,
        "price": close_price,
        "deviation": 20,
        "magic": pos.magic,
        "comment": f"Close {reason}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        profit = result.profit  # Approx, mieux utiliser history
        logging.info(f"{symbol} : Position fermée {pos.ticket} profit {profit}")
        send_telegram_alert(f"❌ Position fermée {symbol} ticket {pos.ticket} profit {profit}", force=True)
        outcome = "win" if profit > 0 else "loss" if profit < 0 else "breakeven"
        update_trade_on_close(pos.ticket, profit, outcome)
    else:
        logging.error(f"{symbol} : Échec close {pos.ticket} : {result.comment}")