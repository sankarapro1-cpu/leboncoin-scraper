"""
Modèles de base de données avec SQLAlchemy.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    Text, JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class SearchProfile(Base):
    """Profil de recherche personnalisé par l'utilisateur."""
    __tablename__ = "search_profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Filtres
    brand = Column(String(100))           # ex: "Renault", "Peugeot"
    model = Column(String(100))           # ex: "Clio", "208"
    min_price = Column(Integer)
    max_price = Column(Integer)
    min_year = Column(Integer)
    max_year = Column(Integer)
    min_km = Column(Integer)
    max_km = Column(Integer)
    fuel_type = Column(String(50))        # essence, diesel, hybride, electrique
    transmission = Column(String(50))    # manuelle, automatique
    max_owners = Column(Integer)
    location_city = Column(String(100))
    location_radius_km = Column(Integer, default=100)
    keywords = Column(String(500))       # mots-clés supplémentaires
    excluded_keywords = Column(String(500))  # mots à exclure

    # Relation avec les annonces
    listings = relationship("Listing", back_populates="search_profile")


class Listing(Base):
    """Annonce Leboncoin scrapée."""
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    leboncoin_id = Column(String(50), nullable=False, unique=True)
    search_profile_id = Column(Integer, ForeignKey("search_profiles.id"))
    scraped_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)  # False si annonce supprimée

    # Données brutes de l'annonce
    title = Column(String(500))
    url = Column(String(1000))
    price = Column(Integer)               # en euros
    price_is_negotiable = Column(Boolean, default=False)
    thumbnail_url = Column(String(1000))
    description = Column(Text)
    published_at = Column(DateTime)

    # Caractéristiques véhicule
    brand = Column(String(100))
    model = Column(String(100))
    year = Column(Integer)
    mileage = Column(Integer)             # en km
    fuel_type = Column(String(50))
    transmission = Column(String(50))
    doors = Column(Integer)
    seats = Column(Integer)
    color = Column(String(50))
    owners_count = Column(Integer)
    technical_control = Column(Boolean)   # CT valide
    first_hand = Column(Boolean)

    # Localisation
    city = Column(String(100))
    department = Column(String(50))
    postal_code = Column(String(10))
    latitude = Column(Float)
    longitude = Column(Float)

    # Vendeur
    seller_type = Column(String(20))      # "private" ou "pro"
    seller_name = Column(String(200))

    # Analyse & scoring
    opportunity_score = Column(Integer, default=0)   # 0-100
    price_score = Column(Integer, default=0)         # score basé sur prix vs marché
    quality_score = Column(Integer, default=0)       # qualité de l'annonce
    urgency_score = Column(Integer, default=0)       # mots-clés urgence
    market_avg_price = Column(Integer)               # prix moyen marché pour ce véhicule
    price_deviation_pct = Column(Float)              # % sous/sur la moyenne
    estimated_resale_price = Column(Integer)         # prix de revente estimé
    potential_margin = Column(Integer)               # marge potentielle en €
    potential_margin_pct = Column(Float)             # marge potentielle en %
    score_details = Column(JSON)                     # détail du scoring

    # Statut utilisateur
    is_saved = Column(Boolean, default=False)
    is_contacted = Column(Boolean, default=False)
    is_purchased = Column(Boolean, default=False)
    user_note = Column(Text)
    alert_sent = Column(Boolean, default=False)

    search_profile = relationship("SearchProfile", back_populates="listings")
    price_history = relationship("PriceHistory", back_populates="listing")

    __table_args__ = (
        Index("idx_listings_score", "opportunity_score"),
        Index("idx_listings_scraped", "scraped_at"),
        Index("idx_listings_active", "is_active"),
    )


class PriceHistory(Base):
    """Historique des changements de prix d'une annonce."""
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"))
    price = Column(Integer, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    listing = relationship("Listing", back_populates="price_history")


class MarketData(Base):
    """Données marché agrégées par modèle (pour calcul de moyenne)."""
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True)
    brand = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    mileage_range = Column(String(50))    # ex: "50000-100000"
    avg_price = Column(Integer)
    min_price = Column(Integer)
    max_price = Column(Integer)
    sample_count = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("brand", "model", "year", "mileage_range"),
        Index("idx_market_model", "brand", "model"),
    )


class ScrapingRun(Base):
    """Log de chaque cycle de scraping."""
    __tablename__ = "scraping_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    status = Column(String(20), default="running")  # running, success, error
    listings_found = Column(Integer, default=0)
    listings_new = Column(Integer, default=0)
    listings_updated = Column(Integer, default=0)
    error_message = Column(Text)
    search_profile_id = Column(Integer, ForeignKey("search_profiles.id"))
