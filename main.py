"""
BOT DE TRADING — STRATÉGIE EMA 20/50
======================================
Symboles : Volatility 25, 50, 75, 100 Index
Stratégie : Croisement EMA20/EMA50 avec filtre de tendance M5,
            2% de risque par trade, break-even + trailing stop ATR.
"""

import MetaTrader5 as mt5
import time
import logging
import threading
from datetime import datetime

from config import SYMBOL, ACCOUNT_NUMBER
from utils import setup_logging
from database import init_db
from connexion import connect_to_mt5, disconnect
from strategy import (
    get_signal,
    open_trade,
    monitor_active_trade,
    is_volatility_good,
    prepare_trade_request,
    _mt5_lock,          # Mutex partagé entre strategy et main
)

# Import multi-comptes
try:
    from multi_account import MultiAccountManager
    from accounts_config import ACCOUNTS, MODE
    MULTI_ACCOUNT_AVAILABLE = True
except ImportError:
    MULTI_ACCOUNT_AVAILABLE = False
    MODE = "SINGLE"
    logging.warning("⚠️ accounts_config.py non trouvé — Mode SINGLE activé")


# ═══════════════════════════════════════════════════════════════
# EXÉCUTION TRADE (single ou multi-comptes)
# ═══════════════════════════════════════════════════════════════

def execute_trade(symbol: str, signal: dict, multi_manager=None) -> tuple:
    """
    Exécute le trade sur un ou plusieurs comptes.
    Returns: (ticket, lot, account_number)
    """
    if multi_manager and MODE == "MULTI":
        request, lot, entry_price = prepare_trade_request(symbol, signal)
        if request is None:
            return None, 0, None

        results = multi_manager.execute_trade_all_accounts(request)

        if results:
            first   = results[0]
            acc_num = first.get("account", ACCOUNT_NUMBER)
            logging.info(f"✅ Trades exécutés sur {len(results)} compte(s)")
            return first.get("ticket"), lot, acc_num
        else:
            logging.error(f"❌ Aucun trade exécuté (multi-comptes)")
            return None, 0, None
    else:
        ticket, lot = open_trade(symbol, signal)
        return ticket, lot, ACCOUNT_NUMBER


# ═══════════════════════════════════════════════════════════════
# BOUCLE D'ANALYSE PAR SYMBOLE
# ═══════════════════════════════════════════════════════════════

def run_bot_for_symbol(symbol: str, multi_manager=None):
    """
    Thread indépendant d'analyse et de trading pour un symbole.
    """
    logging.info(f"🔍 Démarrage analyse | {symbol}")

    while True:
        try:
            # ── Vérification connexion MT5 ──
            with _mt5_lock:
                info = mt5.terminal_info()
            if not info or not info.connected:
                logging.warning(f"[{symbol}] MT5 non connecté, attente...")
                time.sleep(5)
                continue

            # ── Filtre de volatilité ──
            vol_ok, reason = is_volatility_good(symbol)
            if not vol_ok:
                logging.debug(f"[{symbol}] {reason}")
                time.sleep(300)
                continue

            # ── Position déjà ouverte sur ce symbole ? ──
            with _mt5_lock:
                existing = mt5.positions_get(symbol=symbol)
            if existing:
                logging.debug(f"[{symbol}] Position déjà ouverte, surveillance...")
                time.sleep(10)
                continue

            # ── Analyse du signal ──
            signal = get_signal(symbol)

            if signal:
                logging.info(
                    f"🎯 [{symbol}] SIGNAL {signal['type']} | {signal['reason']}"
                )

                ticket, lot, acc_num = execute_trade(symbol, signal, multi_manager)

                if ticket:
                    monitor_active_trade(symbol, ticket, lot, signal, acc_num)
                else:
                    logging.error(f"❌ Échec ouverture trade | {symbol}")

            time.sleep(10)

        except Exception as e:
            logging.error(f"❌ Exception thread [{symbol}] : {e}", exc_info=True)
            time.sleep(10)


# ═══════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    setup_logging(
        level=logging.INFO,
        console_level=logging.INFO,
        file_level=logging.DEBUG,
    )

    # Initialisation DB
    init_db()

    # Gestion multi-comptes
    multi_manager = None

    if MULTI_ACCOUNT_AVAILABLE and MODE == "MULTI":
        logging.info("🔗 Mode MULTI-COMPTES activé")
        multi_manager      = MultiAccountManager(ACCOUNTS)
        connection_results = multi_manager.connect_all()
        connected_count    = sum(1 for v in connection_results.values() if v)
        logging.info(f"✅ {connected_count}/{len(ACCOUNTS)} compte(s) connecté(s)")

        # Connexion du compte principal pour les analyses
        if not connect_to_mt5():
            logging.error("❌ Échec connexion compte principal")
            exit(1)
    else:
        if not connect_to_mt5():
            logging.error("❌ Échec connexion MT5")
            exit(1)

    logging.info("=" * 65)
    logging.info(f"🚀 BOT DÉMARRÉ (Mode: {MODE})")
    logging.info(f"📊 Stratégie : EMA 20/50 Crossover | 2% risque | R:R 1:2")
    logging.info(f"⏰ Timeframes : M5 (tendance) + M1 (signal)")
    logging.info(f"📈 Symboles : {', '.join(SYMBOL)}")
    logging.info("=" * 65)

    # Démarrage d'un thread par symbole
    threads = []
    for symbol in SYMBOL:
        t = threading.Thread(
            target=run_bot_for_symbol,
            args=(symbol, multi_manager),
            name=f"Thread-{symbol}",
            daemon=True,
        )
        t.start()
        threads.append(t)
        time.sleep(2)   # Décalage pour éviter les pics de charge au démarrage

    # Boucle principale — maintient le process vivant
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        logging.info("⏹️ Arrêt demandé par l'utilisateur...")
        for t in threads:
            t.join(timeout=2)
    finally:
        if multi_manager:
            multi_manager.disconnect_all()
        disconnect()
        logging.info("🛑 Bot arrêté proprement")
