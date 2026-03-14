# 🚗 AutoDeal — Analyseur d'annonces Leboncoin

Outil privé pour détecter automatiquement les véhicules sous-évalués sur Leboncoin.
Scraping intelligent + scoring des opportunités + alertes en temps réel.

---

## Architecture

```
leboncoin-scraper/
├── backend/
│   ├── main.py         # API FastAPI (endpoints + dashboard HTML)
│   ├── scraper.py      # Scraper Playwright anti-détection
│   ├── scoring.py      # Moteur de scoring 0-100
│   ├── alerts.py       # Alertes email + Telegram
│   ├── scheduler.py    # Scraping périodique (APScheduler)
│   ├── models.py       # Modèles SQLAlchemy
│   ├── database.py     # Connexion DB
│   └── config.py       # Configuration (.env)
├── frontend/
│   ├── templates/
│   │   ├── index.html      # Dashboard principal
│   │   └── settings.html   # Gestion profils de recherche
│   └── static/
│       ├── style.css       # Thème sombre
│       └── app.js          # Alpine.js (interactivité)
├── data/               # Base de données SQLite (générée)
├── .env.example        # Template de configuration
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Installation rapide

### 1. Prérequis
- Python 3.12+
- (Optionnel) Docker

### 2. Installation sans Docker

```bash
# Cloner le projet
git clone <url> && cd leboncoin-scraper

# Créer l'environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -r requirements.txt

# Installer le navigateur Chromium
playwright install chromium

# Configurer
cp .env.example .env
# Éditez .env avec vos paramètres

# Lancer
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Installation avec Docker

```bash
cp .env.example .env
# Éditez .env

docker-compose up -d
```

Accédez à : **http://localhost:8000**

---

## Configuration

Copiez `.env.example` en `.env` et ajustez :

| Variable | Description | Défaut |
|----------|-------------|--------|
| `SCRAPE_INTERVAL_MINUTES` | Fréquence du scraping | `15` |
| `ALERT_SCORE_THRESHOLD` | Score minimum pour alerte | `70` |
| `MAX_LISTINGS_PER_CYCLE` | Annonces max par scan | `200` |
| `SMTP_*` | Config email Gmail | — |
| `TELEGRAM_BOT_TOKEN` | Token bot Telegram | — |
| `TELEGRAM_CHAT_ID` | ID chat Telegram | — |
| `PROXY_LIST` | Proxies rotatifs (optionnel) | — |

### Configuration Telegram (recommandé)
1. Ouvrez Telegram → cherchez **@BotFather** → `/newbot`
2. Copiez le token dans `TELEGRAM_BOT_TOKEN`
3. Cherchez **@userinfobot** pour obtenir votre `TELEGRAM_CHAT_ID`

### Configuration Email Gmail
1. Activez la validation en 2 étapes sur votre compte Google
2. Allez dans Sécurité → **Mots de passe d'application**
3. Créez un mot de passe pour "Autre" → copiez dans `SMTP_PASSWORD`

---

## Utilisation

### 1. Créer un profil de recherche
- Allez dans **Paramètres** → **Nouveau profil**
- Définissez : marque, modèle, prix max, km max, localisation...
- Activez le profil

### 2. Lancer un scan
- Cliquez sur **▶ Lancer scan** dans la sidebar
- Ou attendez le scan automatique (toutes les 15 min)

### 3. Analyser les résultats
- **Dashboard** : Meilleures affaires en temps réel
- **Annonces** : Liste filtrée avec tri par score/prix/marge
- Cliquez sur une annonce pour voir l'analyse complète

### 4. Score d'opportunité (0-100)
| Critère | Points max |
|---------|-----------|
| Prix vs moyenne marché | 40 |
| Mots-clés urgence vendeur | 20 |
| Qualité annonce (CT, 1ère main...) | 20 |
| Fraîcheur (annonce récente) | 10 |
| Ratio km/âge | 10 |

---

## API REST

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Statistiques dashboard |
| `GET /api/listings` | Liste annonces (filtres, pagination) |
| `GET /api/listings/best-deals` | Top meilleures affaires |
| `POST /api/scrape/start` | Lancer un scan manuellement |
| `GET /api/scrape/status` | Historique des scans |
| `GET /api/profiles` | Profils de recherche |
| `POST /api/profiles` | Créer un profil |
| `GET /api/alerts/stream` | SSE temps réel |

Documentation interactive : **http://localhost:8000/docs**

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.12 + FastAPI |
| Scraping | Playwright (Chromium headless) |
| Parser | BeautifulSoup4 + JSON Next.js |
| Base de données | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLAlchemy 2.0 |
| Planificateur | APScheduler |
| Frontend | HTML + Alpine.js + CSS pur |
| Alertes | SMTP + Telegram Bot API |
| Conteneur | Docker + docker-compose |

---

## Notes légales

Cet outil est à usage **strictement privé et personnel**.
Le scraping doit respecter les CGU de Leboncoin et le `robots.txt`.
Limitez la fréquence des requêtes pour ne pas surcharger les serveurs.
