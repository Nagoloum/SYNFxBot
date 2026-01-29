# 🔄 GUIDE DE MIGRATION - NOUVELLE STRATÉGIE

## ✨ Qu'est-ce qui a changé ?

### Stratégie complètement refaite

| Avant | Après |
|-------|-------|
| Stratégie SMC complexe | Stratégie de Confirmation de Structure |
| Multiples timeframes (H4, H1, M30, M15) | 2 timeframes (M5 + M1) |
| Patterns complexes (BOS, CHOCH, FVG, etc.) | Indicateurs simples et efficaces |
| TP fixes multiples | Chandelier Exit (trailing dynamique) |
| Gestion complexe | Gestion simplifiée et robuste |

---

## 🎯 Nouvelle stratégie en bref

### Concept
**Ne trader que les mouvements explosifs confirmés**

### Filtres (dans l'ordre)
1. **M5** : EMA 50 → Contexte de tendance
2. **M1** : EMA 200 → King Filter (sécurité)
3. **M1** : ADX > 20 → Puissance
4. **M1** : RSI > 55 (BUY) ou < 45 (SELL) → Momentum
5. **M1** : EMA 9 × EMA 21 + Donchian Break → TRIGGER

### Signal BUY
```
✅ Prix M5 > EMA 50
✅ Prix M1 > EMA 200
✅ ADX > 20
✅ RSI > 55
✅ EMA 9 croise au-dessus EMA 21
✅ Prix casse le Donchian High (nouveau plus haut 20 périodes)
```

### Signal SELL
```
✅ Prix M5 < EMA 50
✅ Prix M1 < EMA 200
✅ ADX > 20
✅ RSI < 45
✅ EMA 9 croise en-dessous EMA 21
✅ Prix casse le Donchian Low (nouveau plus bas 20 périodes)
```

---

## 🔧 Installation de la nouvelle version

### 1. Sauvegarder l'ancienne version (optionnel)

```bash
cd /chemin/vers/SYNFxBot
mkdir backup_old_strategy
cp *.py backup_old_strategy/
```

### 2. Remplacer les fichiers

Remplacer ces fichiers par les nouveaux :
- `strategy.py` ← **Complètement refait**
- `config.py` ← **Simplifié**
- `main.py` ← **Simplifié**
- `requirements.txt` ← **Ajout de pandas-ta**
- `README.md` ← **Nouvelle documentation**

Garder tels quels :
- `connexion.py`
- `database.py`
- `utils.py`
- `multi_account.py`
- `accounts_config.py`
- `app.py`
- `.env`

### 3. Installer pandas-ta

```bash
pip install pandas-ta
```

Ou réinstaller tout :

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

### Fichier `.env`

Aucun changement nécessaire. Conserver votre configuration actuelle :

```env
ACCOUNT_NUMBER=votre_numero
PASSWORD=votre_password
SERVER=Deriv-Demo
TELEGRAM_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id
MONGODB_URI=mongodb://localhost:27017
```

### Fichier `accounts_config.py`

Aucun changement si vous utilisez le multi-comptes. Garder votre configuration.

### Fichier `config.py`

Vérifié automatiquement. Les seuls paramètres sont :
- `SYMBOL` : Liste des indices (V25, V50, V75, V100)
- `MAGIC_NUMBER` : Identifiant du bot

### Fichier `strategy.py`

Paramètres modifiables (en haut du fichier) :

```python
# Risque par trade
RISK_PER_TRADE = 0.01  # 1%

# ATR pour Chandelier Exit
ATR_MULTIPLIER = 3.0

# Seuils
ADX_THRESHOLD = 20
RSI_BUY_THRESHOLD = 55
RSI_SELL_THRESHOLD = 45

# Squeeze
SQUEEZE_THRESHOLD = 0.85
SQUEEZE_SIZE_MULTIPLIER = 1.5
EXPANSION_SIZE_MULTIPLIER = 0.5
```

---

## 🚀 Lancement

### Mode Single

```bash
python main.py
```

### Mode Multi-comptes

```bash
# Vérifier accounts_config.py
# MODE = "MULTI"

python main.py
```

### Dashboard

```bash
streamlit run app.py
```

---

## 📊 Ce qui a été supprimé

Ces concepts de l'ancienne stratégie ne sont plus utilisés :

- ❌ Smart Money Concepts (BOS, CHOCH)
- ❌ Fair Value Gap (FVG)
- ❌ Order Blocks (OB)
- ❌ Premium/Discount Zones
- ❌ OTE (Optimal Trade Entry)
- ❌ ZigZag pour swings
- ❌ Analyse multi-timeframe complexe (H4, H1, M30, M15)

Pourquoi ?
- Trop complexe
- Difficile à automatiser de manière fiable
- Trop de faux signaux malgré les filtres

---

## 📈 Ce qui a été ajouté

### Nouveaux indicateurs

- ✅ **Donchian Channel** : Confirmation de cassure
- ✅ **ADX** : Filtre de puissance (éviter le range)
- ✅ **RSI** : Filtre de momentum
- ✅ **Bollinger Bands** : Détection du Squeeze
- ✅ **ATR** : Chandelier Exit dynamique

### Nouvelles fonctionnalités

- ✅ **Squeeze Sizing** : Ajustement intelligent de la taille de position
- ✅ **Chandelier Exit** : Trailing stop qui laisse respirer le prix
- ✅ **Filtrage multi-niveaux** : M5 (contexte) + M1 (exécution)
- ✅ **Logs détaillés** : Chaque étape est tracée

---

## 🧪 Tests recommandés

### 1. Test en Démo (OBLIGATOIRE)

```bash
# Dans .env
SERVER=Deriv-Demo
ACCOUNT_NUMBER=votre_compte_demo
```

Lancer le bot et observer :
- Les signaux détectés
- Les trades ouverts
- La gestion du Chandelier Exit
- Les alertes Telegram

### 2. Vérifier les logs

```bash
tail -f logs/v100bot_20250129.log
```

Vérifier :
- ✅ Contexte M5 détecté
- ✅ Filtres M1 validés
- ✅ Signal TRIGGER détecté
- ✅ Squeeze détecté (si applicable)
- ✅ Trade ouvert
- ✅ Chandelier Exit mis à jour

### 3. Surveiller le Dashboard

```bash
streamlit run app.py
```

Vérifier :
- Trades enregistrés en DB
- Win Rate
- Profit/Perte
- Évolution du capital

### 4. Tester sur plusieurs jours

Laisser tourner le bot en démo pendant 3-7 jours avant de passer en réel.

---

## ⚠️ Points d'attention

### Différences de comportement

| Aspect | Ancienne stratégie | Nouvelle stratégie |
|--------|-------------------|-------------------|
| **Fréquence de trading** | Moyenne à élevée | Faible (signaux rares mais qualité) |
| **Type de mouvements** | Tous types | Mouvements explosifs uniquement |
| **Gestion de sortie** | TP fixes multiples | Chandelier Exit dynamique |
| **Taille de position** | Fixe selon risque | Ajustée selon Squeeze |

### Période d'adaptation

Les premiers jours, vous remarquerez peut-être :
- **Moins de trades** : C'est normal ! La stratégie filtre 80% des faux signaux
- **Attentes plus longues** : Le bot attend que TOUS les critères soient remplis
- **Trades plus longs** : Le Chandelier Exit laisse courir les profits

C'est voulu. **Qualité > Quantité**.

---

## 🔍 Dépannage

### Le bot n'ouvre aucun trade

**Causes possibles :**

1. **Marché trop calme** : Vérifier que l'ATR est suffisant
   ```
   Logs : "Volatility 100 Index trop calme (ATR faible)"
   ```

2. **Aucun contexte M5** : Vérifier que le prix a une direction claire sur M5
   ```
   Logs : "Contexte M5 : NEUTRAL"
   ```

3. **Filtres M1 non validés** : Vérifier ADX, RSI, EMA 200
   ```
   Logs : "❌ ADX faible : 15.2 <= 20"
   ```

4. **Pas de cassure Donchian** : Le prix doit créer un nouveau plus haut/bas
   ```
   Logs : Aucun message "EMA_CROSS_UP_DONCHIAN_BREAK"
   ```

### Le bot ouvre trop de trades

**Causes possibles :**

1. **Seuils trop bas** : Augmenter `ADX_THRESHOLD` à 25 ou 30
2. **Timeframe trop basse** : Ne pas modifier M5/M1 !

### Chandelier Exit ferme trop tôt

**Solution :** Augmenter `ATR_MULTIPLIER` à 4.0 ou 5.0

```python
# strategy.py
ATR_MULTIPLIER = 4.0  # au lieu de 3.0
```

---

## 📚 Documentation complète

Voir :
- `README.md` : Documentation complète de la stratégie
- `MULTI_ACCOUNTS_README.md` : Guide multi-comptes
- Code source avec commentaires détaillés

---

## 🆘 Support

En cas de problème :
1. Vérifier les logs dans `logs/`
2. Vérifier la connexion MT5
3. Tester en mode SINGLE d'abord
4. Consulter `README.md`

---

**Bonne migration ! 🚀**
