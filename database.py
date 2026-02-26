"""
Couche de persistance MongoDB — multi-comptes
Structure : trading_bot_{account_number} / {symbol_safe} / documents
"""
import logging
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
from config import MONGODB_URI


class DatabaseManager:
    def __init__(self, uri: str):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.uri    = uri

    def get_db(self, account_number: int):
        """Retourne la base de données propre au compte."""
        return self.client[f"trading_bot_{account_number}"]

    def get_collection(self, account_number: int, symbol: str):
        """
        Retourne la collection pour un compte + symbole.
        Crée l'index unique sur 'ticket' si nécessaire (empêche les doublons).
        """
        db          = self.get_db(account_number)
        safe_symbol = symbol.replace(" ", "_").lower()
        col         = db[safe_symbol]

        # Index unique sur ticket — opération idempotente, inoffensive si déjà présent
        col.create_index([("ticket", ASCENDING)], unique=True, background=True)
        return col


# ── Instance globale ────────────────────────────────────────────
_db_manager: DatabaseManager | None = None


def _get_manager() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(MONGODB_URI)
    return _db_manager


# ═══════════════════════════════════════════════════════════════
# API PUBLIQUE
# ═══════════════════════════════════════════════════════════════

def init_db():
    """Initialise la connexion DB (appelée au démarrage du bot)."""
    try:
        mgr = _get_manager()
        # Test rapide de connectivité
        mgr.client.admin.command('ping')
        logging.info("💾 MongoDB connecté avec succès")
    except Exception as e:
        logging.error(f"❌ Erreur connexion MongoDB : {e}")


def save_open(account_number: int, symbol: str, ticket: int,
              type_trade: str, price: float):
    """
    Enregistre l'ouverture d'un trade.
    Utilise upsert pour éviter les doublons en cas de retry.
    """
    try:
        col = _get_manager().get_collection(account_number, symbol)
        col.update_one(
            {"ticket": ticket},
            {"$setOnInsert": {
                "ticket":     ticket,
                "symbol":     symbol,
                "type":       type_trade,
                "open_price": float(price),
                "open_time":  datetime.utcnow(),
                "status":     "OPEN",
                "account":    account_number,
                "profit":     None,
            }},
            upsert=True
        )
    except Exception as e:
        logging.error(f"save_open [compte {account_number} #{ticket}] : {e}")


def save_close(account_number: int, symbol: str, ticket: int,
               profit: float, price: float, status: str = "CLOSED"):
    """
    Enregistre la fermeture d'un trade avec le profit réel calculé.
    Si le document n'existe pas (sync tardive), il est créé via upsert.
    """
    try:
        col = _get_manager().get_collection(account_number, symbol)
        col.update_one(
            {"ticket": ticket},
            {"$set": {
                "close_price": float(price),
                "close_time":  datetime.utcnow(),
                "profit":      round(float(profit), 2),
                "status":      status,
            }},
            upsert=True
        )
    except Exception as e:
        logging.error(f"save_close [compte {account_number} #{ticket}] : {e}")
