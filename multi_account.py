"""
Module de gestion multi-comptes MT5.
Permet de connecter et d'exécuter des trades sur plusieurs comptes simultanément.

Fix appliqué : utilisation du mutex _mt5_lock depuis strategy.py pour sérialiser
               toutes les opérations MT5 et éviter les conflits entre threads.
"""
import MetaTrader5 as mt5
import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

from database import save_open

# Mutex partagé (importé depuis strategy pour cohérence globale)
# On utilise un lock local ici car strategy n'est pas encore chargé à ce stade
import threading
_local_lock = threading.Lock()


@dataclass
class AccountConfig:
    """Configuration d'un compte MT5."""
    account_number:  int
    password:        str
    server:          str
    name:            str   = ""
    risk_multiplier: float = 1.0   # 1.0 = même lot que le compte maître
    enabled:         bool  = True


class MultiAccountManager:
    """
    Gestionnaire multi-comptes MT5.
    Note : MT5 ne supporte qu'une connexion à la fois par processus.
    On se reconnecte à chaque opération (connect → trade → disconnect).
    """

    def __init__(self, accounts: List[AccountConfig]):
        self.accounts            = accounts
        self.account_info_cache: Dict[int, dict] = {}

    # ── Connexion ──────────────────────────────────────────────

    def connect_all(self) -> Dict[int, bool]:
        """Tente la connexion à tous les comptes activés."""
        results = {}
        for account in self.accounts:
            if not account.enabled:
                logging.info(f"⭕ Compte {account.account_number} désactivé")
                results[account.account_number] = False
                continue
            results[account.account_number] = self.connect_account(account)
        return results

    def connect_account(self, account: AccountConfig) -> bool:
        """Vérifie les identifiants d'un compte et met en cache ses informations."""
        with _local_lock:
            try:
                if mt5.terminal_info():
                    mt5.shutdown()
                    time.sleep(0.5)

                if not mt5.initialize():
                    logging.error(f"❌ Init MT5 échoué pour {account.account_number}: {mt5.last_error()}")
                    return False

                if not mt5.login(account.account_number,
                                 password=account.password,
                                 server=account.server):
                    logging.error(f"❌ Login échoué {account.account_number}: {mt5.last_error()}")
                    mt5.shutdown()
                    return False

                info = mt5.account_info()
                if info is None:
                    logging.error(f"❌ Infos compte indisponibles {account.account_number}")
                    mt5.shutdown()
                    return False

                self.account_info_cache[account.account_number] = {
                    "balance":  info.balance,
                    "equity":   info.equity,
                    "currency": info.currency,
                    "server":   info.server,
                    "name":     account.name or f"Compte {account.account_number}",
                }

                logging.info(
                    f"✅ Compte {account.account_number} ({account.name}) | "
                    f"Solde: {info.balance:.2f} {info.currency}"
                )
                mt5.shutdown()
                return True

            except Exception as e:
                logging.error(f"❌ Exception connexion {account.account_number}: {e}")
                return False

    # ── Exécution des trades ───────────────────────────────────

    def execute_trade_on_account(self, account_number: int,
                                  trade_request: dict) -> Optional[dict]:
        """Exécute un trade sur un compte spécifique (reconnexion → ordre → déconnexion)."""
        account_config = next(
            (a for a in self.accounts if a.account_number == account_number), None
        )
        if not account_config or not account_config.enabled:
            return None

        with _local_lock:
            try:
                # Reconnexion au compte cible
                if mt5.terminal_info():
                    mt5.shutdown()
                    time.sleep(0.3)

                if not mt5.initialize():
                    logging.error(f"❌ Init MT5 échoué pour compte {account_number}")
                    return None

                if not mt5.login(account_config.account_number,
                                 password=account_config.password,
                                 server=account_config.server):
                    logging.error(f"❌ Login échoué {account_number}: {mt5.last_error()}")
                    mt5.shutdown()
                    return None

                # Ajustement du volume selon le multiplicateur de risque
                if account_config.risk_multiplier != 1.0:
                    orig                   = trade_request.get("volume", 0.01)
                    trade_request["volume"] = round(
                        orig * account_config.risk_multiplier,
                        2
                    )
                    logging.info(
                        f"📊 Volume ajusté {account_number}: {orig} → {trade_request['volume']} "
                        f"(×{account_config.risk_multiplier})"
                    )

                result = mt5.order_send(trade_request)
                mt5.shutdown()

                if result is None:
                    logging.error(f"❌ order_send retourné None pour {account_number}")
                    return None

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logging.info(f"✅ Trade exécuté compte {account_number} | Ticket {result.order}")
                    save_open(
                        account_number=account_number,
                        symbol=trade_request["symbol"],
                        ticket=result.order,
                        type_trade="BUY" if trade_request["type"] in [
                            mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT
                        ] else "SELL",
                        price=result.price,
                    )
                    return {
                        "account": account_number,
                        "ticket":  result.order,
                        "volume":  trade_request["volume"],
                        "price":   result.price,
                        "retcode": result.retcode,
                    }
                else:
                    logging.error(f"❌ Échec ordre {account_number}: {result.comment}")
                    return None

            except Exception as e:
                logging.error(f"❌ Exception trade {account_number}: {e}")
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                return None

    def execute_trade_all_accounts(self, trade_request_template: dict) -> List[dict]:
        """Exécute le même trade sur tous les comptes actifs."""
        results = []
        for account in self.accounts:
            if not account.enabled:
                continue
            # Copie indépendante pour chaque compte
            result = self.execute_trade_on_account(
                account.account_number,
                trade_request_template.copy()
            )
            if result:
                results.append(result)
            time.sleep(0.5)
        return results

    # ── Utilitaires ────────────────────────────────────────────

    def get_account_info(self, account_number: int) -> Optional[dict]:
        return self.account_info_cache.get(account_number)

    def get_all_accounts_info(self) -> Dict[int, dict]:
        return self.account_info_cache.copy()

    def disconnect_all(self):
        try:
            with _local_lock:
                if mt5.terminal_info():
                    mt5.shutdown()
            logging.info("🔌 Tous les comptes déconnectés")
        except Exception as e:
            logging.error(f"❌ Erreur déconnexion : {e}")
