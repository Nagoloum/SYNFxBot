"""
SCRIPT DE TEST - VÉRIFICATION DE L'INSTALLATION
================================================
Vérifie que toutes les dépendances sont installées
et que la configuration de base fonctionne.
"""

import sys
import os

print("=" * 65)
print("🔍 VÉRIFICATION DE L'INSTALLATION")
print("=" * 65)
print()

# ═══════════════════════════════════════════════════════════════
# 1. VÉRIFICATION DES MODULES PYTHON
# ═══════════════════════════════════════════════════════════════

print("📦 Vérification des modules Python...")
modules_required = [
    "MetaTrader5",
    "pandas",
    "pandas_ta",
    "numpy",
    "pymongo",
    "python-dotenv",
    "telegram",
    "streamlit",
]

missing_modules = []

for module_name in modules_required:
    try:
        if module_name == "python-dotenv":
            import dotenv
            print(f"  ✅ {module_name}")
        elif module_name == "MetaTrader5":
            import MetaTrader5 as mt5
            print(f"  ✅ {module_name}")
        elif module_name == "pandas_ta":
            import pandas_ta as ta
            print(f"  ✅ {module_name}")
        else:
            __import__(module_name)
            print(f"  ✅ {module_name}")
    except ImportError:
        print(f"  ❌ {module_name} - MANQUANT")
        missing_modules.append(module_name)

print()

if missing_modules:
    print("❌ Modules manquants détectés !")
    print("   Installer avec : pip install -r requirements.txt")
    print()
else:
    print("✅ Tous les modules sont installés")
    print()

# ═══════════════════════════════════════════════════════════════
# 2. VÉRIFICATION DU FICHIER .env
# ═══════════════════════════════════════════════════════════════

print("🔐 Vérification du fichier .env...")

if not os.path.exists(".env"):
    print("  ❌ Fichier .env introuvable")
    print("     Créer avec : cp .env.example .env")
    print("     Puis éditer le fichier .env avec vos identifiants")
    print()
else:
    print("  ✅ Fichier .env trouvé")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    # Vérification des variables essentielles
    required_vars = ["ACCOUNT_NUMBER", "PASSWORD", "SERVER"]
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var, "")
        if not value or value == "":
            print(f"     ❌ {var} non configuré")
            missing_vars.append(var)
        else:
            # Masquer les valeurs sensibles
            if var == "PASSWORD":
                display_value = "***"
            elif var == "ACCOUNT_NUMBER":
                display_value = value
            else:
                display_value = value[:20] + "..." if len(value) > 20 else value
            print(f"     ✅ {var} = {display_value}")
    
    print()
    
    if missing_vars:
        print("  ⚠️  Certaines variables sont manquantes. Éditer le fichier .env")
        print()

# ═══════════════════════════════════════════════════════════════
# 3. VÉRIFICATION DES FICHIERS
# ═══════════════════════════════════════════════════════════════

print("📁 Vérification des fichiers...")

required_files = [
    "main.py",
    "strategy.py",
    "config.py",
    "connexion.py",
    "database.py",
    "utils.py",
    "multi_account.py",
    "accounts_config.py",
    "requirements.txt",
]

for file in required_files:
    if os.path.exists(file):
        print(f"  ✅ {file}")
    else:
        print(f"  ❌ {file} - MANQUANT")

print()

# ═══════════════════════════════════════════════════════════════
# 4. TEST DE CONNEXION MT5 (OPTIONNEL)
# ═══════════════════════════════════════════════════════════════

print("🔌 Test de connexion MT5 (optionnel)...")
print("   Note : MT5 doit être installé et le terminal doit être fermé.")
print()

try:
    import MetaTrader5 as mt5
    from dotenv import load_dotenv
    
    load_dotenv()
    
    account_number = int(os.getenv("ACCOUNT_NUMBER", "0"))
    password = os.getenv("PASSWORD", "")
    server = os.getenv("SERVER", "")
    
    if account_number == 0 or password == "":
        print("  ⏭️  Configuration MT5 incomplète, test ignoré")
        print()
    else:
        if not mt5.initialize():
            print(f"  ❌ Échec initialisation MT5")
            print(f"     Erreur : {mt5.last_error()}")
            print()
        else:
            print("  ✅ MT5 initialisé")
            
            # Tentative de connexion
            authorized = mt5.login(account_number, password=password, server=server)
            
            if not authorized:
                print(f"  ❌ Échec connexion compte {account_number}")
                print(f"     Erreur : {mt5.last_error()}")
                print(f"     Vérifier : ACCOUNT_NUMBER, PASSWORD, SERVER dans .env")
            else:
                account_info = mt5.account_info()
                print(f"  ✅ Connecté au compte {account_number}")
                print(f"     Serveur : {account_info.server}")
                print(f"     Solde : {account_info.balance} {account_info.currency}")
            
            mt5.shutdown()
            print()

except Exception as e:
    print(f"  ⚠️  Erreur lors du test MT5 : {e}")
    print()

# ═══════════════════════════════════════════════════════════════
# 5. VÉRIFICATION MONGODB (OPTIONNEL)
# ═══════════════════════════════════════════════════════════════

print("🗄️  Test de connexion MongoDB (optionnel)...")

try:
    from pymongo import MongoClient
    from dotenv import load_dotenv
    
    load_dotenv()
    
    mongodb_uri = os.getenv("MONGODB_URI", "")
    
    if not mongodb_uri:
        print("  ⏭️  MONGODB_URI non configuré, test ignoré")
        print()
    else:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        
        # Test de connexion
        client.server_info()
        print("  ✅ MongoDB connecté")
        print(f"     URI : {mongodb_uri[:30]}...")
        
        client.close()
        print()

except Exception as e:
    print(f"  ⚠️  Erreur MongoDB : {e}")
    print(f"     MongoDB n'est pas obligatoire. Le bot peut fonctionner sans.")
    print()

# ═══════════════════════════════════════════════════════════════
# 6. RÉSUMÉ
# ═══════════════════════════════════════════════════════════════

print("=" * 65)
print("📊 RÉSUMÉ")
print("=" * 65)
print()

if missing_modules:
    print("❌ Installation incomplète")
    print("   Actions requises :")
    print("   1. Installer les modules manquants : pip install -r requirements.txt")
else:
    print("✅ Tous les modules Python sont installés")

if not os.path.exists(".env"):
    print("❌ Configuration incomplète")
    print("   Actions requises :")
    print("   1. Créer le fichier .env : cp .env.example .env")
    print("   2. Éditer .env avec vos identifiants MT5")
else:
    print("✅ Fichier .env trouvé")

print()

if not missing_modules and os.path.exists(".env"):
    print("🚀 Vous êtes prêt à lancer le bot !")
    print()
    print("   Prochaines étapes :")
    print("   1. Vérifier .env (ACCOUNT_NUMBER, PASSWORD, SERVER)")
    print("   2. Tester en mode DEMO d'abord")
    print("   3. Lancer avec : python main.py")
    print("   4. Dashboard : streamlit run app.py")
    print()
else:
    print("⚠️  Configuration à compléter avant de lancer le bot")
    print()

print("=" * 65)
print("📚 Documentation : README.md, MIGRATION_GUIDE.md, QUICK_START.md")
print("=" * 65)
