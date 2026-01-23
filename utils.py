# utils.py - Utilitaires pour logging et Telegram (alertes limitées)
import logging
import os
from datetime import datetime
import asyncio
import sys
from telegram import Bot
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


def setup_logging():
    """Configure logging : fichier quotidien + console"""
    if not os.path.exists("logs"):
        os.makedirs("logs")

    log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_filename, encoding="utf-8")
        ],
        force=True
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.WARNING)
    # logging.info("Logging initialisé")


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