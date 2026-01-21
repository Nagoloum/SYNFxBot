# connection.py - VERSION AMÉLIORÉE ET ROBUSTE
import MetaTrader5 as mt5
import logging
import time
from config import ACCOUNT_NUMBER, PASSWORD, SERVER, MT5_TERMINAL_PATH
from utils import send_telegram_alert  # Alertes optionnelles

def connect_to_mt5(max_retries=3, delay=5):
    """Connexion à MT5 avec retry et logs détaillés"""
    terminal_path = MT5_TERMINAL_PATH or r"C:\Program Files\MetaTrader 5\terminal64.exe"

    for attempt in range(1, max_retries + 1):
        try:
            # Si déjà initialisé, shutdown propre avant retry
            if mt5.terminal_info() is not None:
                mt5.shutdown()
                time.sleep(1)

            # logging.info(f"Tentative de connexion MT5 #{attempt}/{max_retries}...")
            # logging.info(f"Chemin terminal : {terminal_path}")

            if not mt5.initialize(path=terminal_path):
                error = mt5.last_error()
                logging.error(f"Échec initialisation MT5 : {error}")
                if attempt < max_retries:
                    time.sleep(delay)
                    continue
                else:
                    send_telegram_alert(f"❌ Échec définitif connexion MT5 : {error}")
                    return False

            # logging.info("Initialisation MT5 réussie")

            # Login
            if not mt5.login(ACCOUNT_NUMBER, password=PASSWORD, server=SERVER):
                error = mt5.last_error()
                logging.error(f"Échec login compte {ACCOUNT_NUMBER} : {error}")
                mt5.shutdown()
                if attempt < max_retries:
                    time.sleep(delay)
                    continue
                else:
                    send_telegram_alert(f"❌ Échec login MT5 : {error}")
                    return False

            # Infos compte
            account_info = mt5.account_info()
            terminal_info = mt5.terminal_info()

            if account_info is None or terminal_info is None:
                logging.error("Impossible de récupérer infos compte/terminal")
                mt5.shutdown()
                return False

            logging.info(f"Connecté avec succès au compte {ACCOUNT_NUMBER}")
            # logging.info(f"Broker : {terminal_info.company}")
            logging.info(f"Solde : {account_info.balance:.2f} {account_info.currency}")
            logging.info(f"Levier : 1:{account_info.leverage}\n")

            # success_msg = (
            #     f"✅ Connexion MT5 réussie !\n"
            #     f"Compte : {ACCOUNT_NUMBER}\n"
            #     f"Broker : {terminal_info.company}\n"
            #     f"Solde : {account_info.balance:.2f} {account_info.currency}"
            # )
            #print(success_msg)
            # send_telegram_alert(success_msg)

            return True

        except Exception as e:
            logging.error(f"Exception inattendue lors de la connexion MT5 : {e}")
            if attempt < max_retries:
                time.sleep(delay)
            else:
                send_telegram_alert(f"❌ Erreur critique connexion MT5 : {e}")
                return False

    return False

def disconnect():
    """Déconnexion propre de MT5"""
    try:
        if mt5.terminal_info() is not None:
            mt5.shutdown()
            logging.info("=== BOT DE TRADING XAUUSD ARRÉTÉ ===")
            # print("Déconnexion de MT5")
            send_telegram_alert("🛑 Bot de trading arrêté – Déconnexion")
    except Exception as e:
        logging.error(f"Erreur lors de la déconnexion MT5 : {e}")