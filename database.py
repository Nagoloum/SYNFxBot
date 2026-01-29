import logging
from datetime import datetime
from pymongo import MongoClient
from config import MONGODB_URI, DB_NAME, COLLECTION_NAME

# Gestionnaire de connexions global
class DatabaseManager:
    def __init__(self, uri):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.uri = uri
        
    def get_db(self, account_number):
        """Retourne la base de données spécifique au compte"""
        # Nom de DB formaté : trading_bot_{account_number}
        db_name = f"trading_bot_{account_number}"
        return self.client[db_name]

    def get_collection(self, account_number, symbol):
        """Retourne la collection pour un compte et un marché donnés"""
        db = self.get_db(account_number)
        # Nom de collection formaté : symbol (ex: volatility_75_index)
        # Nettoyage du nom du symbole pour éviter les caractères spéciaux
        safe_symbol = symbol.replace(" ", "_").lower()
        return db[safe_symbol]

# Instance globale
db_manager = None

def init_db_manager():
    global db_manager
    try:
        if db_manager is None:
            db_manager = DatabaseManager(MONGODB_URI)
            # logging.info("💾 Database Manager : Initialisé")
    except Exception as e:
        logging.error(f"❌ Erreur Init DB Manager : {e}")

# Fonctions de sauvegarde mises à jour pour le multi-comptes

def save_open(account_number, symbol, ticket, type_trade, price):
    """Enregistre l'ouverture d'un trade dans la DB du compte spécifique"""
    init_db_manager()
    if db_manager:
        try:
            col = db_manager.get_collection(account_number, symbol)
            col.insert_one({
                "ticket": ticket, 
                "symbol": symbol,
                "type": type_trade, 
                "open_price": float(price),
                "open_time": datetime.utcnow(), 
                "status": "OPEN",
                "account": account_number
            })
            # logging.info(f"💾 [Compte {account_number}] Trade {ticket} enregistré.")
        except Exception as e:
            logging.error(f"Erreur insertion DB (Compte {account_number}) : {e}")

def save_close(account_number, symbol, ticket, profit, price, status="CLOSED"):
    """Enregistre la fermeture d'un trade"""
    init_db_manager()
    if db_manager:
        try:
            col = db_manager.get_collection(account_number, symbol)
            col.update_one(
                {"ticket": ticket},
                {"$set": {
                    "close_price": price, 
                    "close_time": datetime.utcnow(), 
                    "profit": profit, 
                    "status": status
                }}
            )
        except Exception as e:
            logging.error(f"Erreur update DB (Compte {account_number}) : {e}")

# Rétro-compatibilité pour le code existant (ne supporte que le compte par défaut/env)
# Cette fonction est dépréciée mais gardée pour éviter de casser le code existant avant refonte totale
def init_db():
    init_db_manager()

# Ces alias pointent vers une version "dummy" ou nécessitent d'être mis à jour dans strategy.py
# On ne peut plus utiliser une variable globale 'collection' unique.
collection = None 
