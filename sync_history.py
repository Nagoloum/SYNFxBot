"""
Synchronisation de l'historique MT5 → MongoDB.
Utile pour rattraper les fermetures manquées ou importer l'historique complet.

Corrections appliquées :
  - save_open utilise désormais upsert → pas de doublons à l'import
  - save_close utilise upsert → fonctionne même si l'ouverture est absente
"""
import MetaTrader5 as mt5
import logging
import time
from datetime import datetime, timedelta

from accounts_config import ACCOUNTS
from database import save_close, save_open
from config import MAGIC_NUMBER

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")


def sync_account(account_config, days: int = 30):
    """Synchronise l'historique d'un compte vers MongoDB."""
    logging.info(
        f"🔄 Synchronisation {account_config.name} ({account_config.account_number})..."
    )

    # ── Connexion ──────────────────────────────────────────────
    if not mt5.initialize():
        logging.error("❌ Erreur init MT5")
        return

    if not mt5.login(account_config.account_number,
                     password=account_config.password,
                     server=account_config.server):
        logging.error(f"❌ Login échoué {account_config.account_number}")
        mt5.shutdown()
        return

    # ── Récupération historique ────────────────────────────────
    from_date = datetime.now() - timedelta(days=days)
    to_date   = datetime.now() + timedelta(days=1)

    deals = mt5.history_deals_get(from_date, to_date)
    mt5.shutdown()

    if deals is None or len(deals) == 0:
        logging.warning(f"⚠️ Aucun historique ({days} derniers jours)")
        return

    count_open  = 0
    count_close = 0

    for deal in deals:
        # Filtre par Magic Number (0 = trades manuels acceptés aussi)
        if MAGIC_NUMBER and deal.magic != MAGIC_NUMBER and deal.magic != 0:
            continue

        symbol = deal.symbol
        ticket = deal.order
        profit = deal.profit
        price  = deal.price

        if deal.entry == mt5.DEAL_ENTRY_IN:
            # Ouverture — upsert pour éviter les doublons
            trade_type = "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL"
            save_open(
                account_config.account_number,
                symbol,
                ticket,
                trade_type,
                price,
            )
            count_open += 1

        elif deal.entry == mt5.DEAL_ENTRY_OUT:
            # Fermeture — upsert pour créer si absent
            save_close(
                account_config.account_number,
                symbol,
                ticket,
                profit,
                price,
                status="CLOSED",
            )
            count_close += 1

    logging.info(
        f"✅ Compte {account_config.account_number} : "
        f"{count_open} ouvertures, {count_close} fermetures synchronisées."
    )
    time.sleep(1)


def main():
    print("=== SYNCHRONISATION DU JOURNAL DE TRADING ===")
    print("Parcourt tous les comptes configurés et met à jour MongoDB.")
    print("⚠️ Arrêtez le bot avant de lancer cette synchronisation.")

    confirm = input("Tapez 'O' pour continuer : ")
    if confirm.strip().lower() != "o":
        print("Annulé.")
        return

    for account in ACCOUNTS:
        if account.enabled:
            sync_account(account)

    print("=== SYNCHRONISATION TERMINÉE ===")


if __name__ == "__main__":
    main()
