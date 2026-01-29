"""
Module de gestion multi-comptes MT5
Permet de connecter et trader sur plusieurs comptes simultanément
"""
import MetaTrader5 as mt5
import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from database import save_open

@dataclass
class AccountConfig:
    """Configuration d'un compte MT5"""
    account_number: int
    password: str
    server: str
    name: str = ""  # Nom optionnel pour identifier le compte
    risk_multiplier: float = 1.0  # Multiplicateur de risque (ex: 0.5 = 50% du risque du compte maître)
    enabled: bool = True  # Activer/désactiver ce compte

class MultiAccountManager:
    """
    Gestionnaire de plusieurs comptes MT5.
    Permet de :
    - Se connecter à plusieurs comptes
    - Exécuter des trades sur tous les comptes actifs
    - Gérer les risques individuellement par compte
    """
    
    def __init__(self, accounts: List[AccountConfig]):
        """
        Initialise le gestionnaire avec une liste de comptes
        
        Args:
            accounts: Liste des configurations de comptes
        """
        self.accounts = accounts
        self.connected_accounts: Dict[int, mt5] = {}
        self.account_info_cache: Dict[int, dict] = {}
        
    def connect_all(self) -> Dict[int, bool]:
        """
        Connecte tous les comptes configurés
        
        Returns:
            Dict avec account_number -> True/False selon succès connexion
        """
        results = {}
        
        for account in self.accounts:
            if not account.enabled:
                logging.info(f"⏭️  Compte {account.account_number} désactivé, ignoré.")
                results[account.account_number] = False
                continue
                
            success = self.connect_account(account)
            results[account.account_number] = success
            
        return results
    
    def connect_account(self, account: AccountConfig) -> bool:
        """
        Connecte un compte spécifique
        
        Args:
            account: Configuration du compte
            
        Returns:
            True si connexion réussie, False sinon
        """
        try:
            # Si déjà connecté, on déconnecte d'abord
            if account.account_number in self.connected_accounts:
                mt5.shutdown()
                time.sleep(1)
            
            # Initialisation MT5
            if not mt5.initialize():
                error = mt5.last_error()
                logging.error(f"❌ Échec init MT5 pour compte {account.account_number}: {error}")
                return False
            
            # Connexion au compte
            if not mt5.login(account.account_number, password=account.password, server=account.server):
                error = mt5.last_error()
                logging.error(f"❌ Échec login compte {account.account_number}: {error}")
                mt5.shutdown()
                return False
            
            # Vérification des infos compte
            account_info = mt5.account_info()
            if account_info is None:
                logging.error(f"❌ Infos compte indisponibles pour {account.account_number}")
                mt5.shutdown()
                return False
            
            # Cache des infos compte
            self.account_info_cache[account.account_number] = {
                "balance": account_info.balance,
                "equity": account_info.equity,
                "margin": account_info.margin,
                "currency": account_info.currency,
                "server": account_info.server,
                "name": account.name or f"Compte {account.account_number}"
            }
            
            logging.info(
                f"✅ Connecté compte {account.account_number} ({account.name or 'Sans nom'}) | "
                f"Solde: {account_info.balance:.2f} {account_info.currency}"
            )
            
            # Note: On ne garde pas l'instance MT5 ouverte car MT5 ne supporte qu'une connexion à la fois
            # On se reconnectera à chaque trade
            mt5.shutdown()
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Exception lors connexion compte {account.account_number}: {e}")
            return False
    
    def execute_trade_on_account(self, account_number: int, trade_request: dict) -> Optional[dict]:
        """
        Exécute un trade sur un compte spécifique
        
        Args:
            account_number: Numéro du compte
            trade_request: Dictionnaire de requête MT5 (comme dans open_trade)
            
        Returns:
            Résultat de l'ordre ou None si échec
        """
        account_config = next((acc for acc in self.accounts if acc.account_number == account_number), None)
        if not account_config or not account_config.enabled:
            logging.warning(f"⚠️  Compte {account_number} non configuré ou désactivé")
            return None
        
        try:
            # Connexion au compte
            if not mt5.initialize():
                logging.error(f"❌ Échec init MT5 pour compte {account_number}")
                return None
            
            if not mt5.login(account_config.account_number, password=account_config.password, server=account_config.server):
                logging.error(f"❌ Échec login compte {account_number}")
                mt5.shutdown()
                return None
            
            # Ajustement du volume selon le multiplicateur de risque
            if account_config.risk_multiplier != 1.0:
                original_volume = trade_request.get("volume", 0.1)
                trade_request["volume"] = float(original_volume) * account_config.risk_multiplier
                logging.info(
                    f"📊 Volume ajusté compte {account_number}: {original_volume} -> {trade_request['volume']:.3f} "
                    f"(multiplier: {account_config.risk_multiplier})"
                )
            
            # Envoi de l'ordre
            result = mt5.order_send(trade_request)
            
            # Déconnexion
            mt5.shutdown()
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logging.info(f"✅ Trade exécuté sur compte {account_number} | Ticket: {result.order}")
                
                # Sauvegarde en base de données (Multi-comptes)
                save_open(
                    account_number=account_number,
                    symbol=trade_request["symbol"],
                    ticket=result.order,
                    type_trade="BUY" if trade_request["type"] in [mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT] else "SELL",
                    price=result.price
                )
                
                return {
                    "account": account_number,
                    "ticket": result.order,
                    "volume": trade_request["volume"],
                    "price": result.price,
                    "retcode": result.retcode
                }
            else:
                logging.error(f"❌ Échec trade compte {account_number}: {result.comment}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Exception lors trade compte {account_number}: {e}")
            mt5.shutdown()
            return None
    
    def execute_trade_all_accounts(self, trade_request_template: dict) -> List[dict]:
        """
        Exécute le même trade sur tous les comptes actifs
        
        Args:
            trade_request_template: Template de requête MT5 (sera copié pour chaque compte)
            
        Returns:
            Liste des résultats (un par compte)
        """
        results = []
        
        for account in self.accounts:
            if not account.enabled:
                continue
            
            # Copie de la requête pour éviter modification mutuelle
            trade_request = trade_request_template.copy()
            
            result = self.execute_trade_on_account(account.account_number, trade_request)
            if result:
                results.append(result)
            
            # Petit délai entre les comptes pour éviter surcharge
            time.sleep(0.5)
        
        return results
    
    def get_account_info(self, account_number: int) -> Optional[dict]:
        """Récupère les infos d'un compte depuis le cache"""
        return self.account_info_cache.get(account_number)
    
    def get_all_accounts_info(self) -> Dict[int, dict]:
        """Récupère les infos de tous les comptes"""
        return self.account_info_cache.copy()
    
    def disconnect_all(self):
        """Déconnecte tous les comptes"""
        try:
            if mt5.terminal_info():
                mt5.shutdown()
            logging.info("🔌 Tous les comptes déconnectés")
        except Exception as e:
            logging.error(f"❌ Erreur lors déconnexion: {e}")
