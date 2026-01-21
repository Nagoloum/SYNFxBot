# config.py
from dotenv import load_dotenv # pyright: ignore[reportMissingImports]
import os

load_dotenv()

# Compte de trading (inchangé)
ACCOUNT_NUMBER = int(os.getenv("ACCOUNT_NUMBER", "0"))
PASSWORD = os.getenv("PASSWORD", "")
SERVER = os.getenv("SERVER", "")

# Params bot
SYMBOL = "XAUUSD"
TIMEFRAME = "H1"  # Main timeframe for zones
TIMEFRAME_M15 = "M30"  # For refining zones
VOLUME = 0.01  # Lot de base, ajusté dynamiquement

# Params stratégie - Removed EMA/RSI, added S/D params
ATR_PERIOD = 14  # For management and volatility check
RISK_PERCENT = 0.01  # 1% du solde par trade
RR_RATIO = 2  # Risk:Reward initial 1:2
MIN_RR = 1.2  # Minimum RR to take trade
TRAILING_MULTIPLIER = 1.2  # Trailing = 1x ATR quand profit > 1x ATR
MIN_CONFIRMATIONS = 2  # At least 2 confirmations for entry
RANGE_THRESHOLD = 1.5  # ATR multiplier for detecting accumulation range (flat)
FVG_THRESHOLD = 0.3  # ATR multiplier for FVG detection
VOLATILITY_MIN = 0.4  # Min ATR ratio to avoid flat markets

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")  # NewsAPI.org
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")  # Alpha Vantage
FRED_API_KEY = os.getenv("FRED_API_KEY", "")  # FRED
FMP_API_KEY = os.getenv("FMP_API_KEY", "")  # FMP

# Seuils pour bias
BIAS_THRESHOLD = 3.0  # Sum scores >3 bullish, < -3 bearish

DEVIATION = 20
MAGIC_NUMBER = 123456

HIGH_IMPACT_PAUSE_MINUTES = 30

BREAKEVEN_MULTIPLIER = 1  # Breakeven quand profit = 1x risque
PARTIAL_CLOSE_PERCENT = 0.5  # Fermer 50% à breakeven

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")