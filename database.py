# database.py - Connexion MongoDB avec logging des trades
import logging
import os
from datetime import datetime
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

from config import MONGODB_URI, DB_NAME, COLLECTION_NAME
from utils import send_telegram_alert

client = None
trades_collection = None


def init_db_connection():
    """Initialise MongoDB"""
    global client, trades_collection

    if not MONGODB_URI:
        logging.warning("MONGODB_URI manquant → DB désactivée")
        return False

    try:
        # Quote password
        if "@" in MONGODB_URI and ":" in MONGODB_URI.split("@")[0]:
            prefix, rest = MONGODB_URI.split("://", 1)
            user_pass, suffix = rest.split("@", 1)
            if ":" in user_pass:
                user, passw = user_pass.split(":", 1)
                safe_pass = quote_plus(passw)
                safe_uri = f"{prefix}://{user}:{safe_pass}@{suffix}"
            else:
                safe_uri = MONGODB_URI
        else:
            safe_uri = MONGODB_URI

        client = MongoClient(safe_uri, serverSelectionTimeoutMS=5000, retryWrites=True, w="majority")
        client.admin.command("ping")
        db = client[DB_NAME]
        trades_collection = db[COLLECTION_NAME]

        logging.info("MongoDB connecté")
        return True

    except Exception as e:
        logging.error(f"Erreur MongoDB : {e}")
        return False


def log_new_trade(symbol, signal, price, sl, tp, volume, ticket=None):
    """Log nouveau trade"""
    if trades_collection is None:
        return None

    trade_data = {
        "timestamp_open": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "signal": signal,
        "entry_price": float(price) if price else None,
        "volume": float(volume),
        "sl": float(sl) if sl else None,
        "tp": float(tp) if tp else None,
        "ticket": ticket,
        "result": "pending",
        "profit": 0.0,
        "status": "open",
    }

    try:
        result = trades_collection.insert_one(trade_data)
        logging.info(f"Trade logué : {symbol} {signal} ID {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        logging.error(f"Échec log trade : {e}")
        return None


def update_trade_on_close(ticket, profit, result="win"):
    """Update trade fermé"""
    if trades_collection is None:
        return

    try:
        update_result = trades_collection.update_one(
            {"ticket": ticket},
            {"$set": {
                "timestamp_close": datetime.utcnow().isoformat(),
                "profit": float(profit),
                "result": result,
                "status": "closed",
            }}
        )
        if update_result.modified_count > 0:
            logging.info(f"Trade {ticket} updated : {result} profit {profit}")
        else:
            logging.warning(f"Trade {ticket} non trouvé")
    except Exception as e:
        logging.error(f"Échec update trade {ticket} : {e}")


if not init_db_connection():
    logging.warning("MongoDB désactivé")