# utils.py - Utilitaires pour logging et Telegram (alertes limitées)
import logging
import os
from datetime import datetime
import asyncio
import sys
from telegram import Bot
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

def setup_logging(
    level=logging.INFO,
    console_level=logging.INFO,      # niveau pour la console (peut être plus verbeux)
    file_level=logging.DEBUG,        # niveau pour le fichier (plus détaillé)
    log_dir="logs"
):
    """
    Configure le logging :
      - Console : INFO ou DEBUG selon besoin (immédiatement visible)
      - Fichier : un log par jour avec niveau DEBUG (tout est tracé)
    """
    # Création du dossier logs si inexistant
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Nom du fichier log quotidien
    today = datetime.now().strftime("%Y%m%d")
    log_filename = os.path.join(log_dir, f"v100bot_{today}.log")

    # Format commun (plus lisible)
    log_format = "%(asctime)s | %(levelname)-7s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)  # niveau minimum global

    # Supprime les anciens handlers pour éviter les doublons
    root_logger.handlers.clear()

    # 1. Handler console (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(console_handler)

    # 2. Handler fichier
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt=date_format
    ))
    root_logger.addHandler(file_handler)

    # Réduire le bruit de certaines bibliothèques
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("pandas").setLevel(logging.WARNING)

    # Message de démarrage visible
    logging.info("━" * 65)


    return root_logger

def send_telegram_alert(message: str, force=True):
    """Envoie alerte Telegram seulement pour événements clés (launch, close bot, open/close position)"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Config Telegram manquante")
        return

    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message.strip(), parse_mode="HTML"))
    except Exception as e:
        logging.error(f"Échec Telegram : {e}")