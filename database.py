import logging
from datetime import datetime
from pymongo import MongoClient
from config import MONGODB_URI, DB_NAME, COLLECTION_NAME

collection = None

def init_db():
    global collection
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        collection = client[DB_NAME][COLLECTION_NAME]
        # logging.info("💾 MongoDB : Connecté")
    except Exception as e:
        logging.error(f"❌ Erreur MongoDB : {e}")
# database.py

def save_open(ticket, type_trade, price): # Ajoute type_trade ici
    if collection is not None:
        try:
            collection.insert_one({
                "ticket": ticket, 
                "type": type_trade, # Utilise l'argument reçu
                "open_price": float(price),
                "open_time": datetime.utcnow(), 
                "status": "OPEN"
            })
            # logging.info(f"💾 Trade {ticket} enregistré en base.")
        except Exception as e:
            logging.error(f"Erreur insertion DB : {e}")

def save_close(ticket, profit, price):
    if collection is not None:
        collection.update_one(
            {"ticket": ticket},
            {"$set": {"close_price": price, "close_time": datetime.utcnow(), "profit": profit, "status": "CLOSED"}}
        )