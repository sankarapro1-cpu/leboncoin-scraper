"""
Moteur de scoring des opportunités.

Score 0-100 calculé à partir de :
- Écart de prix par rapport à la moyenne du marché (40 pts max)
- Mots-clés d'urgence du vendeur (20 pts max)
- Qualité de l'annonce et infos disponibles (20 pts max)
- Ancienneté de l'annonce (10 pts max)
- Ratio kilométrage/âge (10 pts max)
"""
import re
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from models import Listing, MarketData

logger = logging.getLogger(__name__)

# Mots-clés urgence
URGENCY_KEYWORDS = [
    "urgent", "rapidement", "vite", "déménagement", "départ", "retraite",
    "cause retraite", "cause déménagement", "obligation", "pressé",
    "à saisir", "vends vite", "besoin rapide", "nécessité", "quitte",
    "libère rapidement", "départ à l'étranger", "part à l'étranger",
    "mutation professionnelle"
]

# Mots-clés positifs (qualité)
QUALITY_POSITIVE = [
    "première main", "1ère main", "1 propriétaire", "carnet d'entretien",
    "suivi concessionnaire", "révisé", "contrôle technique ok", "ct ok",
    "ct valide", "sans accident", "non fumeur", "garage",
    "jamais accidenté", "véhicule de collection"
]

# Mots-clés négatifs (problèmes)
QUALITY_NEGATIVE = [
    "accidenté", "à réparer", "pour pièce", "pièces détachées",
    "ne roule pas", "moteur hs", "boîte hs", "à réviser",
    "frein", "choc", "rayure importante", "carrosserie"
]

# Marges de revente typiques par budget d'achat (approximatives)
RESALE_MARGIN_MAP = [
    (3000,  0.30),   # < 3 000€  → 30% marge
    (6000,  0.25),   # < 6 000€  → 25% marge
    (10000, 0.20),   # < 10 000€ → 20% marge
    (15000, 0.18),   # < 15 000€ → 18% marge
    (25000, 0.15),   # < 25 000€ → 15% marge
    (float("inf"), 0.12),  # > 25 000€ → 12% marge
]


def get_expected_margin_rate(price: int) -> float:
    """Retourner le taux de marge de revente attendu selon le prix d'achat."""
    for threshold, rate in RESALE_MARGIN_MAP:
        if price < threshold:
            return rate
    return 0.12


def calculate_mileage_score(year: Optional[int], mileage: Optional[int]) -> int:
    """
    Score basé sur le ratio km/âge (10 pts max).
    Moyenne : ~15 000 km/an
    """
    if not year or not mileage:
        return 5  # neutre si données manquantes
    age = datetime.now().year - year
    if age <= 0:
        return 10
    avg_expected_km = age * 15000
    ratio = mileage / avg_expected_km if avg_expected_km > 0 else 1
    # Moins de km que prévu = bon
    if ratio < 0.5:
        return 10   # très peu de km
    elif ratio < 0.75:
        return 8
    elif ratio < 1.0:
        return 6
    elif ratio < 1.5:
        return 4
    else:
        return 1    # beaucoup trop de km


def calculate_urgency_score(text: str) -> int:
    """
    Score basé sur mots-clés urgence (20 pts max).
    """
    if not text:
        return 0
    text_lower = text.lower()
    matches = sum(1 for kw in URGENCY_KEYWORDS if kw in text_lower)
    if matches == 0:
        return 0
    elif matches == 1:
        return 8
    elif matches == 2:
        return 15
    else:
        return 20


def calculate_quality_score(listing_data: dict) -> int:
    """
    Score qualité de l'annonce (20 pts max).
    Bonus pour photos, CT valide, premier propriétaire, etc.
    Malus pour mots-clés négatifs.
    """
    score = 10  # Score de base

    text = " ".join([
        str(listing_data.get("title", "")),
        str(listing_data.get("description", ""))
    ]).lower()

    # CT valide
    if listing_data.get("technical_control"):
        score += 3
    # Premier propriétaire
    if listing_data.get("first_hand") or listing_data.get("owners_count", 99) == 1:
        score += 3
    # Carnet d'entretien & qualité
    positive_hits = sum(1 for kw in QUALITY_POSITIVE if kw in text)
    score += min(positive_hits * 2, 6)
    # Malus pour problèmes
    negative_hits = sum(1 for kw in QUALITY_NEGATIVE if kw in text)
    score -= min(negative_hits * 3, 12)

    return max(0, min(20, score))


def calculate_recency_score(published_at: Optional[datetime]) -> int:
    """
    Score basé sur la fraîcheur de l'annonce (10 pts max).
    Plus une annonce est récente, mieux c'est.
    """
    if not published_at:
        return 5
    # Rendre aware si naive
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    age_hours = (now - published_at).total_seconds() / 3600

    if age_hours < 1:
        return 10    # Moins d'une heure
    elif age_hours < 6:
        return 9
    elif age_hours < 24:
        return 7
    elif age_hours < 48:
        return 5
    elif age_hours < 72:
        return 3
    else:
        return 1     # Plus de 3 jours


def calculate_price_score(
    price: Optional[int],
    market_avg: Optional[int],
    good_deal_threshold: float = 0.85,
) -> tuple[int, float]:
    """
    Score basé sur l'écart de prix vs marché (40 pts max).
    Retourne (score, deviation_pct).
    deviation_pct < 0 = moins cher que la moyenne (BIEN)
    """
    if not price or not market_avg:
        return 0, 0.0
    deviation = (price - market_avg) / market_avg  # Négatif = moins cher
    # Plus c'est sous la moyenne, meilleur est le score
    if deviation <= -0.40:
        score = 40   # 40%+ sous la moyenne
    elif deviation <= -0.30:
        score = 35
    elif deviation <= -0.20:
        score = 28
    elif deviation <= -0.15:
        score = 22
    elif deviation <= -0.10:
        score = 16
    elif deviation <= -0.05:
        score = 10
    elif deviation <= 0.05:
        score = 6    # Dans la moyenne
    elif deviation <= 0.15:
        score = 3
    else:
        score = 0    # Plus cher que la moyenne
    return score, deviation


def get_market_average(
    db: Session,
    brand: Optional[str],
    model: Optional[str],
    year: Optional[int],
    mileage: Optional[int],
) -> Optional[int]:
    """
    Calculer le prix moyen du marché pour un modèle donné.
    Cherche d'abord dans MarketData, puis calcule depuis les annonces existantes.
    """
    if not brand or not model:
        return None

    # Chercher dans les données marché pré-calculées
    if year:
        mileage_range = _get_mileage_range(mileage)
        market = db.query(MarketData).filter(
            and_(
                func.lower(MarketData.brand) == brand.lower(),
                func.lower(MarketData.model) == model.lower(),
                MarketData.year == year,
                MarketData.mileage_range == mileage_range,
            )
        ).first()
        if market and market.avg_price:
            return market.avg_price

    # Calculer depuis les annonces existantes (±3 ans, ±50 000 km)
    query = db.query(func.avg(Listing.price)).filter(
        and_(
            func.lower(Listing.brand) == brand.lower() if brand else True,
            func.lower(Listing.model) == model.lower() if model else True,
            Listing.price.isnot(None),
            Listing.is_active == True,
        )
    )
    if year:
        query = query.filter(Listing.year.between(year - 2, year + 2))
    if mileage:
        query = query.filter(Listing.mileage.between(max(0, mileage - 50000), mileage + 50000))

    result = query.scalar()
    return int(result) if result else None


def update_market_data(db: Session, brand: str, model: str, year: int):
    """
    Mettre à jour les données marché pour un modèle depuis les annonces en base.
    Appelé périodiquement pour recalculer les moyennes.
    """
    from models import MarketData
    from sqlalchemy import text

    mileage_ranges = [
        (0, 50000, "0-50000"),
        (50000, 100000, "50000-100000"),
        (100000, 150000, "100000-150000"),
        (150000, 200000, "150000-200000"),
        (200000, 999999, "200000+"),
    ]

    for min_km, max_km, range_label in mileage_ranges:
        stats = db.query(
            func.avg(Listing.price),
            func.min(Listing.price),
            func.max(Listing.price),
            func.count(Listing.id),
        ).filter(
            and_(
                func.lower(Listing.brand) == brand.lower(),
                func.lower(Listing.model) == model.lower(),
                Listing.year == year,
                Listing.mileage.between(min_km, max_km),
                Listing.price.isnot(None),
                Listing.is_active == True,
            )
        ).first()

        if stats and stats[3] >= 3:  # Au moins 3 annonces
            existing = db.query(MarketData).filter(
                and_(
                    func.lower(MarketData.brand) == brand.lower(),
                    func.lower(MarketData.model) == model.lower(),
                    MarketData.year == year,
                    MarketData.mileage_range == range_label,
                )
            ).first()
            if existing:
                existing.avg_price = int(stats[0])
                existing.min_price = int(stats[1])
                existing.max_price = int(stats[2])
                existing.sample_count = stats[3]
                existing.updated_at = datetime.utcnow()
            else:
                db.add(MarketData(
                    brand=brand, model=model, year=year,
                    mileage_range=range_label,
                    avg_price=int(stats[0]),
                    min_price=int(stats[1]),
                    max_price=int(stats[2]),
                    sample_count=stats[3],
                ))
    db.commit()


def _get_mileage_range(mileage: Optional[int]) -> str:
    if not mileage:
        return "0-50000"
    if mileage < 50000:
        return "0-50000"
    elif mileage < 100000:
        return "50000-100000"
    elif mileage < 150000:
        return "100000-150000"
    elif mileage < 200000:
        return "150000-200000"
    else:
        return "200000+"


def score_listing(listing_data: dict, db: Optional[Session] = None) -> dict:
    """
    Calculer le score complet d'une annonce.
    Retourne un dict avec tous les scores et l'analyse.
    """
    price = listing_data.get("price")
    brand = listing_data.get("brand")
    model = listing_data.get("model")
    year = listing_data.get("year")
    mileage = listing_data.get("mileage")
    published_at = listing_data.get("published_at")
    title = listing_data.get("title", "")
    description = listing_data.get("description", "")
    full_text = f"{title} {description}"

    # Obtenir la moyenne du marché
    market_avg = None
    if db:
        market_avg = get_market_average(db, brand, model, year, mileage)

    # Calculer les sous-scores
    price_score, price_deviation = calculate_price_score(price, market_avg)
    urgency_score = calculate_urgency_score(full_text)
    quality_score = calculate_quality_score(listing_data)
    recency_score = calculate_recency_score(published_at)
    mileage_score = calculate_mileage_score(year, mileage)

    # Score total
    total_score = price_score + urgency_score + quality_score + recency_score + mileage_score

    # Calcul marge potentielle
    estimated_resale = None
    potential_margin = None
    potential_margin_pct = None
    if price:
        margin_rate = get_expected_margin_rate(price)
        estimated_resale = int(price * (1 + margin_rate))
        # Si le véhicule est sous-côté, la marge réelle est encore meilleure
        if market_avg and price < market_avg:
            # Prix de revente basé sur la moyenne marché + marge négociant
            estimated_resale = int(market_avg * 1.05)  # 5% au-dessus de la moyenne
        potential_margin = estimated_resale - price
        potential_margin_pct = (potential_margin / price) * 100 if price > 0 else 0

    return {
        "opportunity_score": min(100, total_score),
        "price_score": price_score,
        "quality_score": quality_score,
        "urgency_score": urgency_score,
        "market_avg_price": market_avg,
        "price_deviation_pct": round(price_deviation * 100, 1) if price_deviation else None,
        "estimated_resale_price": estimated_resale,
        "potential_margin": potential_margin,
        "potential_margin_pct": round(potential_margin_pct, 1) if potential_margin_pct else None,
        "score_details": {
            "price_score": price_score,
            "urgency_score": urgency_score,
            "quality_score": quality_score,
            "recency_score": recency_score,
            "mileage_score": mileage_score,
        },
    }
