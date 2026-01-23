import MetaTrader5 as mt5
import time
import logging
from config import SYMBOL, LOT_SIZE, MAGIC_NUMBER
from utils import setup_logging, send_telegram_alert
from database import init_db, save_open, save_close 
from connexion import connect_to_mt5, disconnect

# --- CONFIGURATION SÉCURITÉ ---
MAX_ALLOWED_SPREAD = 0.60  # Ne pas ouvrir si le spread est trop élevé

def get_filling_mode():
    """Détermine le mode de remplissage supporté"""
    symbol_info = mt5.symbol_info(SYMBOL)
    if not symbol_info: return 1
    filling_mode = symbol_info.filling_mode
    if filling_mode & 1: return mt5.ORDER_FILLING_FOK
    elif filling_mode & 2: return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_FOK

def open_trade_v100():
    """Ouvre une position BUY avec vérification du spread"""
    mt5.symbol_select(SYMBOL, True)
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logging.error("Prix indisponible")
        return None

    # Vérification du spread (Ask - Bid)
    spread = tick.ask - tick.bid
    if spread > MAX_ALLOWED_SPREAD:
        logging.warning(f"⚠️ Spread trop élevé : {spread:.2f}. Entrée annulée.")
        return None

    vol = float(LOT_SIZE)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": vol,
        "type": mt5.ORDER_TYPE_BUY,
        "price": tick.ask,
        "magic": MAGIC_NUMBER,
        "comment": "Bot 1min V100",
        "type_filling": get_filling_mode(),
        "type_time": mt5.ORDER_TIME_GTC,
    }
    
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        msg = f"🚀 POSITION OUVERTE | Ticket: {result.order} | Prix: {result.price} | Spread: {spread:.2f}"
        logging.info(msg)
        send_telegram_alert(msg, force=True)
        # Enregistrement avec les noms de colonnes synchronisés
        save_open(result.order, "BUY", result.price)
        return result.order
    else:
        err = result.comment if result else mt5.last_error()
        logging.error(f"❌ Erreur Ouverture : {err}")
        return None

def close_trade_v100(ticket):
    """Ferme la position et calcule le profit final"""
    positions = mt5.positions_get(ticket=ticket)
    if not positions: return

    pos = positions[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    # Pour fermer un BUY, on vend au prix BID
    price_close = tick.bid 
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": pos.volume,
        "type": mt5.ORDER_TYPE_SELL,
        "position": ticket,
        "price": price_close,
        "magic": MAGIC_NUMBER,
        "type_filling": get_filling_mode(),
        "type_time": mt5.ORDER_TIME_GTC,
    }
    
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        time.sleep(1) # Attente sync historique
        
        # FORMULE DU PROFIT : (Prix Fermeture - Prix Ouverture) * Volume
        # Le spread est inclus car on ouvre au Ask et ferme au Bid
        history = mt5.history_deals_get(ticket=result.order)
        if history:
            real_profit = history[0].profit
        else:
            real_profit = (price_close - pos.price_open) * pos.volume
            
        msg = f"✅ POSITION FERMÉE | Ticket: {ticket} | Profit: {real_profit:.2f} USD"
        logging.info(msg)
        send_telegram_alert(msg, force=True)
        save_close(ticket, real_profit, price_close)

if __name__ == "__main__":
    setup_logging()
    init_db() 
    if connect_to_mt5():
        logging.info(f"=== BOT V100 LANCÉ | LOT: {LOT_SIZE} ===")
        try:
            while True:
                if not mt5.terminal_info().connected:
                    connect_to_mt5()
                    continue
                
                ticket = open_trade_v100()
                if ticket:
                    logging.info("Position ouverte... attente de 60s")
                    time.sleep(60)
                    close_trade_v100(ticket)
                
                time.sleep(2) # Pause sécurité entre cycles
        except KeyboardInterrupt:
            logging.info("Arrêt bot")
        finally:
            disconnect()