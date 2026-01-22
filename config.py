# config.py - Configuration pour le bot multi-symboles Volatility Indices
from dotenv import load_dotenv
import os

load_dotenv()

# Compte MT5
ACCOUNT_NUMBER = int(os.getenv("ACCOUNT_NUMBER", "0"))
PASSWORD = os.getenv("PASSWORD", "")
SERVER = os.getenv("SERVER", "")

# Symboles gérés (Volatility Indices - adapte aux noms exacts de ton broker)
SYMBOLS = [
    "Volatility 25 Index",  # Tranquille
    "Volatility 50 Index",  # Tranquille
    "Volatility 75 Index",  # Agressif
    "Volatility 100 Index"  # Agressif
]

# Presets par type de symbole
PRESETS = {
    "tranquille": {  # Pour 25 et 50
        "RISK_PERCENT": 0.005,  # 0.5% risque par trade
        "TRAILING_MULTIPLIER": 1.5,
        "VOLATILITY_LOW": 0.7,
        "VOLATILITY_HIGH": 1.8
    },
    "agressif": {  # Pour 75 et 100
        "RISK_PERCENT": 0.01,   # 1% risque par trade
        "TRAILING_MULTIPLIER": 1.2,
        "VOLATILITY_LOW": 0.6,
        "VOLATILITY_HIGH": 2.0
    }
}

# Params communs
TIMEFRAME_H4 = "H4"  # Pour bias
TIMEFRAME_H1 = "H1"  # Pour entrées
ATR_PERIOD = 14
EMA_PERIOD = 50  # Pour bias H4
ATR_WINDOW_AVG = 100  # Pour filtre volatilité
MIN_RR = 1.5
SL_MULTIPLIER = 1.2  # 1-1.5x ATR
TP_MULTIPLIER = 2.0  # RR 2
BREAKEVEN_MULTIPLIER = 1.0
PARTIAL_CLOSE_PERCENT = 0.5
RSI_PERIOD = 14  # Pour confirmation optionnelle
RSI_OVERBOUGHT = 60
RSI_OVERSOLD = 40
MAX_POSITIONS_PER_SYMBOL = 3
DAILY_LOSS_LIMIT = -0.04  # -4% stop daily

DEVIATION = 20
MAGIC_NUMBER = 123456

# Telegram et MT5
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")

# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("MONGODB_DB", "trading_bot")
COLLECTION_NAME = os.getenv("MONGODB_COLLECTION", "trades")