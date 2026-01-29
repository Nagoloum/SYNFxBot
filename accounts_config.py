"""
Configuration des comptes de trading.
Ce fichier remplace la gestion unique via .env pour les comptes.
"""
import os
from dotenv import load_dotenv
from multi_account import AccountConfig

load_dotenv()

# Liste des comptes
ACCOUNTS = [
    # Compte Principal (chargé depuis .env pour compatibilité)
    AccountConfig(
        account_number=int(os.getenv("ACCOUNT_NUMBER", "0")),
        password=os.getenv("PASSWORD", ""),
        server=os.getenv("SERVER", "Deriv-Server"),
        name="Compte Principal",
        risk_multiplier=1.0,
        enabled=True
    ),
    
    # Ajoutez vos autres comptes ici :
    # AccountConfig(
    #     account_number=12345678,
    #     password="password",
    #     server="Deriv-Server",
    #     name="Compte Secondaire",
    #     risk_multiplier=1.0,
    #     enabled=True
    # ),
]

# Mode d'utilisation : "SINGLE" ou "MULTI"
# Si SINGLE : seul le premier compte de la liste est utilisé
# Si MULTI : tous les comptes activés sont utilisés
if len(ACCOUNTS) == 1:
    MODE = "SINGLE"
else:
    MODE = "MULTI"
