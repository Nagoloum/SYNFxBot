# trader.py - Exécution trades
import MetaTrader5 as mt5
import logging

from config import DEVIATION, MAGIC_NUMBER, SYMBOLS
from strategy import get_preset
from utils import send_telegram_alert
from database import log_new_trade


def calculate_lot_size(symbol, sl_distance_points, account_balance, risk_percent):
    """Calcul lot basé sur risque"""
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info or symbol_info.point == 0:
        return 0.01

    point_value = symbol_info.trade_contract_size * symbol_info.point
    risk_amount = account_balance * risk_percent
    lot_size = risk_amount / (sl_distance_points * point_value)
    return max(round(lot_size, 2), 0.01)


def execute_trade(symbol, signal, sl, tp):
    """Exécute trade sans limite de positions"""  # MODIF: Suppression check max positions pour illimité
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return

    price = tick.ask if signal == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL

    account_info = mt5.account_info()
    if not account_info:
        return

    preset = get_preset(symbol)  # De strategy.py
    risk_percent = preset["RISK_PERCENT"]

    point = mt5.symbol_info(symbol).point
    sl_distance_points = abs(price - sl) / point if point > 0 else 100
    volume = calculate_lot_size(symbol, sl_distance_points, account_info.balance, risk_percent)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": DEVIATION,
        "magic": MAGIC_NUMBER,
        "comment": "Trend Volatility Strat",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"{symbol} : Ordre {signal} échoué : {result.comment}")
    else:
        logging.info(f"{symbol} : {signal} ouvert ticket {result.order}")
        send_telegram_alert(f"✅ Position ouverte {symbol} {signal} ticket {result.order}", force=True)
        log_new_trade(symbol, signal, result.price, result.request.sl, result.request.tp, volume, result.order)