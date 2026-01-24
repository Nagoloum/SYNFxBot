import MetaTrader5 as mt5
import time
import logging
from datetime import datetime
from config import SYMBOL, LOT_SIZE
from utils import setup_logging, send_telegram_alert
from database import init_db
from connexion import connect_to_mt5, disconnect
from strategy import (close_partial_v100, get_smart_signal,
    get_smart_signal, handle_trade_closure, is_volatility_good, move_sl_to_be, open_trade_v100)

def monitor_active_trade(ticket, lot, signal_data):
    """
    Surveille la position ouverte en temps réel pour gérer :
    1. La clôture partielle (50% du volume)
    2. Le passage en Break-Even (sécurisation du SL)
    3. La détection de clôture finale (SL ou TP touché)
    """
    half_done = False
    print(f"👀 Surveillance active du ticket {ticket} lancée...")

    while True:
        # Récupération de l'état de la position
        positions = mt5.positions_get(ticket=ticket)
        
        # Si la position n'existe plus (fermée par SL, TP ou manuellement)
        if not positions:
            handle_trade_closure(ticket, lot, "SL/TP SERVEUR")
            break
        
        pos = positions[0]
        current_price = pos.price_current
        tp_target = pos.tp
        entry_price = pos.price_open
        
        # LOGIQUE DE GESTION PARTIELLE ET BREAK-EVEN
        if not half_done:
            # Calcul de la progression : On vise le niveau tp_half défini par la stratégie
            target_reached = False
            if pos.type == mt5.ORDER_TYPE_BUY:
                target_reached = current_price >= signal_data['tp_half']
            elif pos.type == mt5.ORDER_TYPE_SELL:
                target_reached = current_price <= signal_data['tp_half']
            
            if target_reached:
                print(f"🎯 Objectif partiel atteint pour {ticket}. Exécution de la gestion de risque...")
                
                # 1. Fermeture de 50% du lot
                if close_partial_v100(ticket, pos.volume / 2):
                    # 2. Déplacement du SL au prix d'entrée
                    if move_sl_to_be(ticket):
                        half_done = True
                        msg_be = f"🛡️ SÉCURITÉ : Partiel encaissé et Break-Even activé pour le ticket {ticket}"
                        print(msg_be)
                        send_telegram_alert(msg_be)

        # Petite pause pour ne pas saturer le processeur
        time.sleep(1)

if __name__ == "__main__":
    # Initialisation
    setup_logging()
    init_db() 
    
    if connect_to_mt5():
        print(f"🤖 BOT DE TRADING {SYMBOL} DÉMARRÉ ")
        
        last_notif_time = 0
        
        try:
            while True:
                
                # Vérification de la connexion terminal
                if not mt5.terminal_info().connected:
                    print("⚠️ Connexion MT5 perdue, reconnexion...")
                    connect_to_mt5()
                    time.sleep(5)
                    continue
                
                # Vérification des heures de trading
                vol_ok, vol_msg = is_volatility_good()
                
                if not vol_ok:
                    if time.time() - last_notif_time > 3600:
                        print(f"⚠️ {vol_msg}")
                        send_telegram_alert(f"⚠️ {vol_msg}", force=True)
                        last_notif_time = time.time()
                    time.sleep(300)  # Attendre 5 minutes avant de revérifier
                    continue

                # Vérifier si une position du bot est déjà en cours sur le symbole
                existing_positions = mt5.positions_get(symbol=SYMBOL)
                
                if not existing_positions:
                    # Analyse du marché pour trouver un signal SMC + OTE + FVG
                    signal = get_smart_signal()
                    
                    if signal:
                        print(f"🔥 Signal détecté : {signal['reason']} sur {signal['tf']}")
                        # On adapte le signal pour open_trade_v100
                        # On ajoute des niveaux de secours si non fournis par la figure
                        if 'sl' not in signal:
                            signal['sl'] = mt5.symbol_info_tick(SYMBOL).ask - 15.0
                            signal['tp'] = mt5.symbol_info_tick(SYMBOL).ask + 45.0
                            signal['tp_half'] = mt5.symbol_info_tick(SYMBOL).ask + 20.0
                            
                        ticket, lot = open_trade_v100(signal)
                        if ticket:
                            monitor_active_trade(ticket, lot, signal)
                
                # Fréquence de scan du marché (toutes le 5 secondes)
                time.sleep(5)

        except KeyboardInterrupt:
            print("🛑 Arrêt du bot par l'utilisateur.")
            if existing_positions:
                for pos in existing_positions:
                    handle_trade_closure(pos.ticket, pos.volume, "ARRÊT BOT")
        finally:
            disconnect()