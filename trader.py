# trader.py - Adapted to take SL/TP from signal, lot dynamic on risk
import MetaTrader5 as mt5
import logging
from config import SYMBOL, DEVIATION, MAGIC_NUMBER, RISK_PERCENT
from utils import send_telegram_alert

def calculate_lot_size(sl_distance_points, account_balance):
    symbol_info = mt5.symbol_info(SYMBOL)
    point_value = symbol_info.point_value or 1.0
    risk_amount = account_balance * RISK_PERCENT
    lot_size = risk_amount / (sl_distance_points * point_value)
    lot_size = max(round(lot_size, 2), 0.01)
    return lot_size

def execute_trade(signal, sl=None, tp=None):
    if not mt5.symbol_select(SYMBOL, True):
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return

    price = tick.ask if signal == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL

    # Use provided SL/TP
    if sl is None or tp is None:
        logging.error("SL/TP not provided")
        return

    account_info = mt5.account_info()
    if not account_info:
        return

    point = mt5.symbol_info(SYMBOL).point
    sl_distance_points = abs(price - sl) / point if point > 0 else 100

    lot_size = calculate_lot_size(sl_distance_points, account_info.balance)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": DEVIATION,
        "magic": MAGIC_NUMBER,
        "comment": "Stratégie S/D SMC",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"ÉCHEC ordre {signal} : {result.comment}")
    else:
        logging.info(f"SUCCÈS → {signal} {lot_size} lots {SYMBOL} | Ticket #{result.order}")
        send_telegram_alert(f"✅ {signal} {lot_size} lots XAUUSD\nPrix: {result.price:.2f}\nSL: {result.sl:.2f} | TP: {result.tp:.2f}")