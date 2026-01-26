import MetaTrader5 as mt5
import time
import logging
from datetime import datetime
from config import SYMBOL
from utils import setup_logging
from database import init_db
from connexion import connect_to_mt5, disconnect
import threading
from strategy import ( get_smart_signal, monitor_active_trade,
    get_smart_signal, is_volatility_good, open_trade)


def run_bot_for_symbol(symbol):
    """Boucle d'analyse indépendante pour chaque indice"""
    logging.info(f"🚀 Analyse du marché {symbol}")
    
    while True:
        try:
            if not mt5.terminal_info().connected:
                time.sleep(5)
                continue

            # Vérification de la volatilité propre à l'indice
            vol_ok, _ = is_volatility_good(symbol)
            if not vol_ok:
                time.sleep(300)
                continue

            # On ne trade que s'il n'y a pas déjà une position ouverte par le bot sur ce symbole
            existing = mt5.positions_get(symbol=symbol)
            if not existing:
                signal = get_smart_signal(symbol)
                
                if signal:
                    logging.info(f"🔥 [{symbol}] Signal détecté : {signal['reason']}")
                    
                    # Sécurité : Niveaux par défaut si absents
                    tick = mt5.symbol_info_tick(symbol)
                    if 'sl' not in signal:
                        dist = 20.0 # À adapter selon l'indice
                        signal['sl'] = tick.ask - dist if signal['type'] == "BUY" else tick.bid + dist
                        signal['tp'] = tick.ask + (dist*3) if signal['type'] == "BUY" else tick.bid - (dist*3)
                        signal['tp_half'] = tick.ask + dist if signal['type'] == "BUY" else tick.bid - dist

                    ticket, lot = open_trade(symbol, signal)
                    if ticket:
                        # On surveille le trade dans le même thread pour cet indice
                        monitor_active_trade(symbol, ticket, lot, signal)
            
            time.sleep(10) # Scan toutes les 10s pour chaque indice
            
        except Exception as e:
            logging.error(f"Erreur dans le thread {symbol}: {e}")
            time.sleep(10)
            
if __name__ == "__main__":
    # Initialisation
    setup_logging(
        level=logging.INFO,
        console_level=logging.DEBUG,
        file_level=logging.DEBUG,
    )
    init_db() 
    
    if connect_to_mt5():
        threads = []
        logging.info(f"🤖 BOT DE TRADING VOLATILITY DÉMARRÉ ")
                
        threads = []
        for s in SYMBOL:
            t = threading.Thread(target=run_bot_for_symbol, args=(s,), name=f"Thread-{s}")
            t.daemon = True # Le thread s'arrête si le main s'arrête
            t.start()
            threads.append(t)
            time.sleep(2) # Petit délai pour ne pas saturer le processeur au démarrage
        try:
            while True: time.sleep(2)
        except KeyboardInterrupt:
            logging.info("🛑 Arrêt du bot par l'utilisateur.")
            # Fermer les positions si c'est ouvert
            if threads:
                for t in threads:
                    t.join(timeout=1)
        finally:
            disconnect()