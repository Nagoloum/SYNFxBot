import os
from dotenv import load_dotenv

load_dotenv()

# Connexion MT5
ACCOUNT_NUMBER = int(os.getenv("ACCOUNT_NUMBER", "0"))
PASSWORD = os.getenv("PASSWORD", "")
SERVER = os.getenv("SERVER", "")
MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

SYMBOL = ["Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index", "Volatility 100 Index"]
LOT_SIZE = 1.0  # Volume fixe pour le test
MAGIC_NUMBER = 123456

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("MONGODB_DB", "trading_bot_V100")
COLLECTION_NAME = "trades_v100"
