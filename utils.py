# utils.py - VERSION FINALE CORRIGÉE POUR python-telegram-bot v22.5
import logging
import os
from datetime import datetime
import asyncio

# Imports Telegram
from telegram import Bot
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

def setup_logging():
    """Configure les logs : fichier quotidien + console"""
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    log_filename = f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # Désactiver les logs HTTP verbeux
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.WARNING)
    
    # logging.info("Logging initialisé avec succès")

def send_telegram_alert(message: str):
    """Envoie une alerte Telegram de manière synchrone"""
    if not message or not message.strip():
        import traceback
        logging.warning("Tentative d'envoi Telegram avec message vide !")
        logging.warning("Stacktrace de l'appel:\n" + traceback.format_stack(limit=5))
        return

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Config Telegram manquante – Alerte ignorée")
        return

    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        asyncio.run(bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message.strip(),
            parse_mode='HTML',
            disable_web_page_preview=True
        ))
    except Exception as e:
        logging.error(f"Échec envoi Telegram : {e}")