# database.py - VERSION AMÉLIORÉE ET ROBUSTE
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from datetime import datetime
import os
import logging
from dotenv import load_dotenv
from config import SYMBOL, MONGODB_URI, DB_NAME, COLLECTION_NAME
from utils import send_telegram_alert  # Pour alertes optionnelles

load_dotenv()

# Configuration (déjà dans config.py, mais fallback ici)
MONGODB_URI = MONGODB_URI or os.getenv("MONGODB_URI")
DB_NAME = DB_NAME or os.getenv("MONGODB_DB", "trading_bot")
COLLECTION_NAME = COLLECTION_NAME or os.getenv("MONGODB_COLLECTION", "trades")

# Client global
client = None
trades_collection = None

def init_db_connection():
    """Initialise et teste la connexion MongoDB Atlas"""
    global client, trades_collection
    
    if not MONGODB_URI:
        logging.warning("MONGODB_URI non défini → Stockage DB désactivé")
        return False

    try:
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,  # Timeout rapide
            retryWrites=True,
            w="majority"
        )
        # Test connexion
        client.admin.command('ping')
        db = client[DB_NAME]
        trades_collection = db[COLLECTION_NAME]
        
        logging.info("Connexion MongoDB Atlas réussie !")
        send_telegram_alert("🗄️ Connexion MongoDB Atlas établie")
        return True

    except ConnectionFailure as e:
        logging.error(f"Échec connexion MongoDB Atlas : {e}")
        send_telegram_alert(f"❌ Échec connexion MongoDB : {e}")
        return False
    except Exception as e:
        logging.error(f"Erreur inattendue MongoDB : {e}")
        return False

def log_new_trade(signal, price, sl, tp, volume, ticket=None):
    """Log un nouveau trade à l'ouverture"""
    if trades_collection is None:
        logging.warning("DB non initialisée → Trade non logué")
        return None

    trade_data = {
        'timestamp_open': datetime.utcnow().isoformat(),
        'signal': signal,
        'symbol': SYMBOL,
        'entry_price': float(price) if price is not None else None,
        'volume': float(volume),
        'sl': float(sl) if sl is not None else None,
        'tp': float(tp) if tp is not None else None,
        'ticket': ticket,  # Ticket MT5 pour mise à jour future
        'result': 'pending',
        'profit': 0.0,
        'status': 'open'
    }

    try:
        result = trades_collection.insert_one(trade_data)
        trade_id = result.inserted_id
        logging.info(f"Nouveau trade logué dans MongoDB (ID: {trade_id}, Ticket: {ticket})")
        send_telegram_alert(
            f"📈 Nouveau trade {signal}\n"
            f"Prix: {price:.2f} | SL: {sl:.2f} | TP: {tp:.2f}\n"
            f"Volume: {volume} lots"
        )
        return trade_id
    except OperationFailure as e:
        logging.error(f"Échec insertion trade : {e}")
        return None

def update_trade_on_close(ticket, profit, result='win'):
    """Met à jour un trade fermé avec profit et résultat"""
    if trades_collection is None:
        return

    try:
        update_result = trades_collection.update_one(
            {"ticket": ticket},
            {
                "$set": {
                    'timestamp_close': datetime.utcnow().isoformat(),
                    'profit': float(profit),
                    'result': result,  # 'win', 'loss', 'breakeven'
                    'status': 'closed'
                }
            }
        )

        if update_result.modified_count > 0:
            logging.info(f"Trade #{ticket} mis à jour : {result} | Profit {profit:.2f} USD")
            send_telegram_alert(
                f"{'✅' if result == 'win' else '🔴'} Trade fermé #{ticket}\n"
                f"Résultat: {result.upper()} | Profit: {profit:.2f} USD"
            )
        else:
            logging.warning(f"Aucun trade trouvé avec ticket {ticket} pour mise à jour")

    except Exception as e:
        logging.error(f"Échec mise à jour trade #{ticket} : {e}")

# Initialisation automatique au chargement du module
if not init_db_connection():
    logging.warning("Fonctionnalité MongoDB désactivée")