# main.py - Point d'entrée bot multi-symboles
import MetaTrader5 as mt5
import time
import logging
from datetime import datetime, timezone

from config import SYMBOLS
from connexion import connect_to_mt5, disconnect
from strategy import generate_signal
from trader import execute_trade
from utils import setup_logging, send_telegram_alert
from position_manager import manage_positions
from database import init_db_connection  # Pour forcer init


if __name__ == "__main__":
    setup_logging()
    logging.info("=== BOT VOLATILITY INDICES DÉMARRÉ ===")
    send_telegram_alert("🚀 Bot VOLATILITY démarré !", force=True)

    if not connect_to_mt5():
        logging.critical("Échec MT5 → Arrêt")
        exit(1)

    try:
        while True:
            manage_positions()

            for symbol in SYMBOLS:
                if not mt5.symbol_select(symbol, True):
                    continue

                signal_info = generate_signal(symbol)
                if signal_info:
                    signal, sl, tp = signal_info
                    execute_trade(symbol, signal, sl, tp)

            time.sleep(60)  # Check chaque minute

    except KeyboardInterrupt:
        logging.info("Interruption manuelle")
    finally:
        disconnect()