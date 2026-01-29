"""
Script de synchronisation de l'historique MT5 vers la Base de Données.
Utile pour mettre à jour le journal de trading pour tous les comptes,
surtout si le bot n'a pas pu enregistrer la clôture en temps réel.
"""
import MetaTrader5 as mt5
import logging
import time
from datetime import datetime, timedelta
from accounts_config import ACCOUNTS
from database import save_close, save_open
from config import MAGIC_NUMBER

# Configuration du logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def sync_account(account_config, days=30):
    """Synchronise l'historique d'un compte spécifique"""
    logging.info(f"🔄 Synchronisation compte {account_config.name} ({account_config.account_number})...")
    
    # 1. Connexion MT5
    if not mt5.initialize():
        logging.error("❌ Erreur init MT5")
        return

    authorized = mt5.login(
        account_config.account_number, 
        password=account_config.password, 
        server=account_config.server
    )
    
    if not authorized:
        logging.error(f"❌ Échec login compte {account_config.account_number}")
        mt5.shutdown()
        return

    # 2. Récupération historique
    from_date = datetime.now() - timedelta(days=days)
    to_date = datetime.now() + timedelta(days=1) # Futur pour être sûr d'avoir tout
    
    deals = mt5.history_deals_get(from_date, to_date)
    
    if deals is None:
        logging.warning(f"⚠️ Aucun historique trouvé pour les {days} derniers jours")
        mt5.shutdown()
        return

    count_updated = 0
    count_new = 0
    
    for deal in deals:
        # On ne s'intéresse qu'aux deals liés à nos trades (Magic Number) ou manuels si voulu
        # Ici on filtre par Magic Number si défini, sinon on prend tout
        if MAGIC_NUMBER and deal.magic != MAGIC_NUMBER and deal.magic != 0:
            continue
            
        symbol = deal.symbol
        ticket = deal.order # Le ticket de l'ordre d'origine
        profit = deal.profit
        price = deal.price
        
        # Type de deal : 0=BUY, 1=SELL, 2=BALANCE
        if deal.entry == mt5.DEAL_ENTRY_OUT: # Sortie (Clôture)
            # C'est une fermeture -> Update DB
            save_close(
                account_config.account_number, 
                symbol, 
                ticket, 
                profit, 
                price, 
                status="CLOSED"
            )
            count_updated += 1
            
        elif deal.entry == mt5.DEAL_ENTRY_IN: # Entrée (Ouverture)
            # C'est une ouverture -> Insert DB (si pas déjà présent)
            # Note: save_open ne vérifie pas l'existence, il insère. 
            # Idéalement il faudrait vérifier, mais pour l'instant on suppose que le bot l'a fait.
            # Si on veut forcer l'import d'historique ancien, on pourrait le faire ici.
            pass

    logging.info(f"✅ Compte {account_config.account_number} : {count_updated} trades mis à jour.")
    mt5.shutdown()
    time.sleep(1) # Pause entre les comptes

def main():
    print("=== SYNCHRONISATION DU JOURNAL DE TRADING ===")
    print("Ce script va parcourir tous les comptes configurés et mettre à jour la base de données.")
    print("⚠️ Assurez-vous que le Bot n'est pas en train de trader activement (risque de déconnexion).")
    
    confirm = input("Tapez 'O' pour continuer : ")
    if confirm.lower() != 'o':
        print("Annulé.")
        return

    for account in ACCOUNTS:
        if account.enabled:
            sync_account(account)
            
    print("=== SYNCHRONISATION TERMINÉE ===")

if __name__ == "__main__":
    main()
