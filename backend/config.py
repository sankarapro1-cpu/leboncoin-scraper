"""
Configuration centrale du projet.
Toutes les valeurs sont chargées depuis .env
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    # --- Application ---
    APP_SECRET_KEY: str = os.getenv("APP_SECRET_KEY", "change-me-in-production")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # --- Base de données ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/data/leboncoin.db")

    # --- Scraping ---
    # Intervalle de scraping en minutes
    SCRAPE_INTERVAL_MINUTES: int = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "15"))
    # Délai min/max entre requêtes (secondes) pour simuler comportement humain
    SCRAPE_DELAY_MIN: float = float(os.getenv("SCRAPE_DELAY_MIN", "2.0"))
    SCRAPE_DELAY_MAX: float = float(os.getenv("SCRAPE_DELAY_MAX", "6.0"))
    # Nombre max d'annonces par cycle
    MAX_LISTINGS_PER_CYCLE: int = int(os.getenv("MAX_LISTINGS_PER_CYCLE", "200"))
    # Utiliser proxy rotatif (optionnel)
    PROXY_LIST: list[str] = [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()]

    # --- Alertes email ---
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "")

    # --- Alertes Telegram ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Scoring des opportunités ---
    # Seuil de score pour déclencher une alerte (0-100)
    ALERT_SCORE_THRESHOLD: int = int(os.getenv("ALERT_SCORE_THRESHOLD", "70"))
    # Pourcentage de décote par rapport à la moyenne pour considérer "bonne affaire"
    GOOD_DEAL_PRICE_THRESHOLD: float = float(os.getenv("GOOD_DEAL_PRICE_THRESHOLD", "0.85"))  # 15% moins cher

    # --- Filtres de recherche par défaut ---
    DEFAULT_MAX_PRICE: int = int(os.getenv("DEFAULT_MAX_PRICE", "20000"))
    DEFAULT_MAX_KM: int = int(os.getenv("DEFAULT_MAX_KM", "200000"))
    DEFAULT_MIN_YEAR: int = int(os.getenv("DEFAULT_MIN_YEAR", "2010"))


settings = Settings()
