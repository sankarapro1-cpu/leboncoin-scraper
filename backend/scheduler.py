"""
Planificateur de scraping périodique.
Utilise APScheduler pour lancer des cycles automatiquement.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from config import settings
from database import get_db_context
from models import SearchProfile, Listing, ScrapingRun
from scraper import run_scrape
from scoring import score_listing, update_market_data
from alerts import send_alerts

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Paris")


async def run_scraping_cycle():
    """
    Cycle complet de scraping :
    1. Charger tous les profils de recherche actifs
    2. Scraper chaque profil
    3. Sauvegarder les nouvelles annonces
    4. Calculer les scores
    5. Envoyer les alertes
    """
    logger.info("=== Début du cycle de scraping ===")

    with get_db_context() as db:
        profiles = db.query(SearchProfile).filter(SearchProfile.is_active == True).all()

        if not profiles:
            logger.warning("Aucun profil de recherche actif trouvé")
            return

        for profile in profiles:
            run = ScrapingRun(
                started_at=datetime.utcnow(),
                status="running",
                search_profile_id=profile.id,
            )
            db.add(run)
            db.commit()
            db.refresh(run)

            try:
                profile_dict = {
                    "brand": profile.brand,
                    "model": profile.model,
                    "min_price": profile.min_price,
                    "max_price": profile.max_price,
                    "min_year": profile.min_year,
                    "max_year": profile.max_year,
                    "max_km": profile.max_km,
                    "fuel_type": profile.fuel_type,
                    "transmission": profile.transmission,
                    "location_city": profile.location_city,
                    "location_radius_km": profile.location_radius_km,
                }

                # Lancer le scraping
                raw_listings = await run_scrape(profile_dict)
                run.listings_found = len(raw_listings)
                logger.info(f"Profil '{profile.name}': {len(raw_listings)} annonces trouvées")

                new_count = 0
                updated_count = 0

                for raw in raw_listings:
                    if not raw.get("leboncoin_id"):
                        continue

                    # Vérifier si l'annonce existe déjà
                    existing = db.query(Listing).filter(
                        Listing.leboncoin_id == raw["leboncoin_id"]
                    ).first()

                    scores = score_listing(raw, db)

                    if existing:
                        # Mettre à jour si le prix a changé
                        if existing.price != raw.get("price"):
                            # Enregistrer l'historique de prix
                            from models import PriceHistory
                            db.add(PriceHistory(listing_id=existing.id, price=existing.price))
                            existing.price = raw.get("price")
                        # Mettre à jour le score
                        existing.opportunity_score = scores["opportunity_score"]
                        existing.price_score = scores["price_score"]
                        existing.quality_score = scores["quality_score"]
                        existing.urgency_score = scores["urgency_score"]
                        existing.market_avg_price = scores["market_avg_price"]
                        existing.price_deviation_pct = scores["price_deviation_pct"]
                        existing.estimated_resale_price = scores["estimated_resale_price"]
                        existing.potential_margin = scores["potential_margin"]
                        existing.potential_margin_pct = scores["potential_margin_pct"]
                        existing.score_details = scores["score_details"]
                        existing.is_active = True
                        db.commit()
                        updated_count += 1
                        listing_obj = existing
                    else:
                        # Créer une nouvelle annonce
                        listing_obj = Listing(
                            search_profile_id=profile.id,
                            **{k: v for k, v in raw.items() if hasattr(Listing, k)},
                            **scores,
                        )
                        db.add(listing_obj)
                        db.commit()
                        db.refresh(listing_obj)
                        new_count += 1

                    # Envoyer alerte si score élevé et nouvelle annonce
                    if new_count > 0 or (existing and scores["opportunity_score"] >= settings.ALERT_SCORE_THRESHOLD):
                        await send_alerts(listing_obj, db)

                    # Mettre à jour les données marché
                    if raw.get("brand") and raw.get("model") and raw.get("year"):
                        update_market_data(db, raw["brand"], raw["model"], raw["year"])

                run.finished_at = datetime.utcnow()
                run.status = "success"
                run.listings_new = new_count
                run.listings_updated = updated_count
                db.commit()

                logger.info(
                    f"Profil '{profile.name}': {new_count} nouvelles annonces, "
                    f"{updated_count} mises à jour"
                )

            except Exception as e:
                logger.error(f"Erreur cycle scraping profil '{profile.name}': {e}")
                run.finished_at = datetime.utcnow()
                run.status = "error"
                run.error_message = str(e)
                db.commit()

    logger.info("=== Fin du cycle de scraping ===")


def start_scheduler():
    """Démarrer le planificateur."""
    scheduler.add_job(
        run_scraping_cycle,
        trigger=IntervalTrigger(minutes=settings.SCRAPE_INTERVAL_MINUTES),
        id="scraping_cycle",
        name="Cycle de scraping Leboncoin",
        replace_existing=True,
        max_instances=1,  # Un seul cycle à la fois
    )
    scheduler.start()
    logger.info(f"Planificateur démarré (intervalle: {settings.SCRAPE_INTERVAL_MINUTES} min)")


def stop_scheduler():
    """Arrêter le planificateur."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Planificateur arrêté")
