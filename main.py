"""
BOT DE TRADING - STRATÉGIE DE CONFIRMATION DE STRUCTURE
========================================================
Stratégie : EMA + Donchian + ADX + RSI + Squeeze + Chandelier Exit
Timeframes : M5 (contexte) + M1 (exécution)
Symboles : Volatility 25, 50, 75, 100 Index
"""

import MetaTrader5 as mt5
import time
import logging
from datetime import datetime
from config import SYMBOL, ACCOUNT_NUMBER
from utils import setup_logging
from database import init_db
from connexion import connect_to_mt5, disconnect
import threading
from strategy import (
    get_smart_signal,
    monitor_active_trade,
    is_volatility_good,
    open_trade,
    prepare_trade_request
)

# Import multi-comptes (optionnel)
try:
    from multi_account import MultiAccountManager
    from accounts_config import ACCOUNTS, MODE
    MULTI_ACCOUNT_AVAILABLE = True
except ImportError:
    MULTI_ACCOUNT_AVAILABLE = False
    MODE = "SINGLE"
    logging.warning("⚠️ Fichier accounts_config.py non trouvé. Mode SINGLE activé par défaut.")


def get_account_number_for_monitoring(multi_account_manager):
    """
    Retourne le numéro de compte à utiliser pour le monitoring.
    En mode multi, retourne le premier compte actif.
    """
    if multi_account_manager and MODE == "MULTI":
        for acc in ACCOUNTS:
            if acc.enabled:
                return acc.account_number
    return ACCOUNT_NUMBER


def execute_trade_with_multi_account(symbol, signal, multi_account_manager=None):
    """
    Exécute un trade en utilisant le système multi-comptes si disponible,
    sinon utilise le système classique.
    """
    if multi_account_manager and MODE == "MULTI":
        request, lot, entry_price, tp1, tp2, tp3 = prepare_trade_request(symbol, signal)
        if request is None:
            return None, 0, None
        
        results = multi_account_manager.execute_trade_all_accounts(request)
        
        if results:
            first_result = results[0]
            account_number = first_result.get("account", ACCOUNT_NUMBER)
            logging.info(f"✅ Trades exécutés sur {len(results)} compte(s)")
            return first_result.get("ticket"), lot, account_number
        else:
            logging.error(f"❌ Aucun trade exécuté sur les comptes")
            return None, 0, None
    else:
        ticket, lot = open_trade(symbol, signal)
        return ticket, lot, ACCOUNT_NUMBER


def run_bot_for_symbol(symbol, multi_account_manager=None):
    """
    Boucle d'analyse indépendante pour chaque indice
    
    Args:
        symbol: Symbole à trader (ex: "Volatility 100 Index")
        multi_account_manager: Gestionnaire multi-comptes (optionnel)
    """
    logging.info(f"🔍 Démarrage analyse | {symbol}")
    
    # Obtenir le numéro de compte pour le monitoring
    account_number = get_account_number_for_monitoring(multi_account_manager)
    
    while True:
        try:
            # Vérification de la connexion MT5
            terminal_info = mt5.terminal_info()
            if not terminal_info or not terminal_info.connected:
                logging.warning(f"⚠️ MT5 non connecté, attente...")
                time.sleep(5)
                continue
            
            # Vérification de la volatilité de l'indice
            vol_ok, reason = is_volatility_good(symbol)
            if not vol_ok:
                logging.debug(f"📊 {symbol} | {reason}")
                time.sleep(300)  # Attendre 5 minutes si marché trop calme
                continue
            
            # Vérifier qu'il n'y a pas déjà une position ouverte sur ce symbole
            existing = mt5.positions_get(symbol=symbol)
            if existing:
                logging.debug(f"⏸️ {symbol} | Position déjà ouverte, surveillance en cours...")
                time.sleep(10)
                continue
            
            # ANALYSE DU SIGNAL
            signal = get_smart_signal(symbol)
            
            if signal:
                logging.info(f"🎯 [{symbol}] SIGNAL DÉTECTÉ | {signal['reason']}")
                logging.info(f"   Type: {signal['type']} | Entry: {signal['entry_price']:.5f}")
                logging.info(f"   SL: {signal['sl']:.5f} | TP: {signal['tp']:.5f}")
                
                # EXÉCUTION DU TRADE
                ticket, lot, acc_num = execute_trade_with_multi_account(
                    symbol, signal, multi_account_manager
                )
                
                if ticket:
                    # SURVEILLANCE DU TRADE
                    logging.info(f"👁️ Démarrage surveillance | Ticket {ticket}")
                    monitor_active_trade(symbol, ticket, lot, signal, acc_num)
                else:
                    logging.error(f"❌ Échec ouverture trade | {symbol}")
            
            # Pause avant prochaine analyse
            time.sleep(10)
        
        except Exception as e:
            logging.error(f"❌ Erreur dans le thread {symbol}: {e}", exc_info=True)
            time.sleep(10)


if __name__ == "__main__":
    # Configuration du logging
    setup_logging(
        level=logging.INFO,
        console_level=logging.INFO,
        file_level=logging.DEBUG,
    )
    
    # Initialisation de la base de données
    init_db()
    
    # Gestion multi-comptes (si disponible)
    multi_account_manager = None
    if MULTI_ACCOUNT_AVAILABLE and MODE == "MULTI":
        logging.info("🔗 Mode MULTI-COMPTES activé")
        multi_account_manager = MultiAccountManager(ACCOUNTS)
        connection_results = multi_account_manager.connect_all()
        
        connected_count = sum(1 for v in connection_results.values() if v)
        logging.info(f"✅ {connected_count}/{len(ACCOUNTS)} compte(s) connecté(s)")
        
        # Connexion du compte principal pour les analyses
        if ACCOUNTS and ACCOUNTS[0].enabled:
            if not connect_to_mt5():
                logging.error("❌ Échec connexion compte principal pour analyses")
                exit(1)
    else:
        # Mode SINGLE : connexion simple
        if not connect_to_mt5():
            logging.error("❌ Échec connexion MT5")
            exit(1)
    
    # Démarrage du bot
    threads = []
    logging.info("=" * 65)
    logging.info(f"🚀 BOT DE TRADING DÉMARRÉ (Mode: {MODE})")
    logging.info(f"📊 Stratégie : Confirmation de Structure")
    logging.info(f"⏰ Timeframes : M5 (contexte) + M1 (exécution)")
    logging.info(f"📈 Symboles : {', '.join(SYMBOL)}")
    logging.info("=" * 65)
    
    # Création d'un thread par symbole
    for symbol in SYMBOL:
        t = threading.Thread(
            target=run_bot_for_symbol,
            args=(symbol, multi_account_manager),
            name=f"Thread-{symbol}",
            daemon=True
        )
        t.start()
        threads.append(t)
        time.sleep(2)  # Décalage entre les démarrages
    
    # Boucle principale
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        logging.info("⏹️ Arrêt du bot par l'utilisateur...")
        for t in threads:
            t.join(timeout=1)
    finally:
        # Déconnexion propre
        if multi_account_manager:
            multi_account_manager.disconnect_all()
        disconnect()
        logging.info("🛑 Bot arrêté")
