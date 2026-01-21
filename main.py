# main.py - Ajoutez cette ligne avec les autres imports
import MetaTrader5 as mt5 
# main.py - VERSION FINALE, CORRIGÉE ET AMÉLIORÉE
import time
import logging
from datetime import datetime, timezone

# Imports corrigés
from config import SYMBOL
from connexion import connect_to_mt5, disconnect
from strategy import generate_signal
from trader import execute_trade
from utils import setup_logging, send_telegram_alert
from position_manager import manage_positions

# Optionnel : Test MongoDB (décommentez si vous utilisez database.py)
# from database import client as mongo_client

# main.py - Updated hours to 6-17
# ... (imports same)

if __name__ == "__main__":
    setup_logging()
    logging.info("=== BOT DE TRADING XAUUSD DÉMARRÉ ===\n")
    send_telegram_alert("🚀 Bot de trading XAUUSD démarré !")

    if not connect_to_mt5():
        logging.critical("Échec connexion MT5 – Arrêt du bot")
        exit()

    try:
        while True:
            manage_positions()

            current_time = datetime.now(timezone.utc)
            signal_info = generate_signal(current_time)
            if signal_info:
                if isinstance(signal_info, tuple):
                    signal, sl, tp = signal_info
                    execute_trade(signal, sl, tp)  # Pass SL/TP to trader
                else:
                    execute_trade(signal_info)

            positions = mt5.positions_get(symbol=SYMBOL)
            sleep_time = 30 if positions and len(positions) > 0 else 60
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logging.info("=== DECONNEXION ===\n")
    finally:
        disconnect()