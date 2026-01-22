# connexion.py - Connexion MT5
import MetaTrader5 as mt5
import logging
import time

from config import ACCOUNT_NUMBER, PASSWORD, SERVER, MT5_TERMINAL_PATH
from utils import send_telegram_alert


def connect_to_mt5(max_retries=3, delay=5):
    """Connexion MT5 avec retries"""
    terminal_path = MT5_TERMINAL_PATH

    for attempt in range(1, max_retries + 1):
        try:
            if mt5.terminal_info():
                mt5.shutdown()
                time.sleep(1)

            logging.info(f"Tentative connexion {attempt}/{max_retries}")
            if not mt5.initialize(path=terminal_path):
                error = mt5.last_error()
                logging.error(f"Init MT5 échoué : {error}")
                continue

            if not mt5.login(ACCOUNT_NUMBER, password=PASSWORD, server=SERVER):
                error = mt5.last_error()
                logging.error(f"Login échoué : {error}")
                mt5.shutdown()
                continue

            account_info = mt5.account_info()
            if account_info is None:
                logging.error("Infos compte indisponibles")
                mt5.shutdown()
                return False

            logging.info(f"Connecté compte {ACCOUNT_NUMBER}")
            send_telegram_alert(f"✅ Bot lancé ! Compte {ACCOUNT_NUMBER}", force=True)  # Alert launch
            return True

        except Exception as e:
            logging.error(f"Exception connexion : {e}")
            time.sleep(delay)

    return False


def disconnect():
    """Déconnexion"""
    try:
        if mt5.terminal_info():
            mt5.shutdown()
        logging.info("Bot arrêté")
        send_telegram_alert("🛑 Bot arrêté", force=True)  # Alert close
    except Exception as e:
        logging.error(f"Erreur déconnexion : {e}")