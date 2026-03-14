"""
API FastAPI - Point d'entrée principal du backend.
"""
import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func
from pathlib import Path

from database import get_db, init_db
from models import SearchProfile, Listing, PriceHistory, ScrapingRun, MarketData
from scoring import score_listing, update_market_data
from scheduler import start_scheduler, stop_scheduler, run_scraping_cycle, scheduler
from config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"

app = FastAPI(
    title="LeBonCoin Car Analyzer",
    description="Outil d'analyse d'annonces automobiles Leboncoin",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ─────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    start_scheduler()
    logger.info("Application démarrée")


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


# ─────────────────────────────────────────────
# Pages HTML
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


# ─────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────

class SearchProfileCreate(BaseModel):
    name: str
    brand: Optional[str] = None
    model: Optional[str] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    min_km: Optional[int] = None
    max_km: Optional[int] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    max_owners: Optional[int] = None
    location_city: Optional[str] = None
    location_radius_km: int = 100
    keywords: Optional[str] = None
    excluded_keywords: Optional[str] = None


class ListingUpdate(BaseModel):
    is_saved: Optional[bool] = None
    is_contacted: Optional[bool] = None
    is_purchased: Optional[bool] = None
    user_note: Optional[str] = None


# ─────────────────────────────────────────────
# API - Profils de recherche
# ─────────────────────────────────────────────

@app.get("/api/profiles")
async def list_profiles(db: Session = Depends(get_db)):
    profiles = db.query(SearchProfile).all()
    return [
        {
            "id": p.id, "name": p.name, "is_active": p.is_active,
            "brand": p.brand, "model": p.model,
            "min_price": p.min_price, "max_price": p.max_price,
            "min_year": p.min_year, "max_year": p.max_year,
            "max_km": p.max_km, "fuel_type": p.fuel_type,
            "transmission": p.transmission, "location_city": p.location_city,
            "location_radius_km": p.location_radius_km,
            "keywords": p.keywords, "excluded_keywords": p.excluded_keywords,
        }
        for p in profiles
    ]


@app.post("/api/profiles")
async def create_profile(data: SearchProfileCreate, db: Session = Depends(get_db)):
    profile = SearchProfile(**data.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"id": profile.id, "name": profile.name, "message": "Profil créé avec succès"}


@app.put("/api/profiles/{profile_id}")
async def update_profile(
    profile_id: int, data: SearchProfileCreate, db: Session = Depends(get_db)
):
    profile = db.query(SearchProfile).filter(SearchProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profil non trouvé")
    for key, value in data.model_dump().items():
        setattr(profile, key, value)
    db.commit()
    return {"message": "Profil mis à jour"}


@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(SearchProfile).filter(SearchProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profil non trouvé")
    profile.is_active = False
    db.commit()
    return {"message": "Profil désactivé"}


@app.post("/api/profiles/{profile_id}/toggle")
async def toggle_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(SearchProfile).filter(SearchProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profil non trouvé")
    profile.is_active = not profile.is_active
    db.commit()
    return {"is_active": profile.is_active}


# ─────────────────────────────────────────────
# API - Annonces
# ─────────────────────────────────────────────

@app.get("/api/listings")
async def list_listings(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, le=100),
    min_score: Optional[int] = Query(None),
    max_price: Optional[int] = Query(None),
    min_year: Optional[int] = Query(None),
    max_km: Optional[int] = Query(None),
    brand: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    fuel_type: Optional[str] = Query(None),
    is_saved: Optional[bool] = Query(None),
    profile_id: Optional[int] = Query(None),
    sort_by: str = Query("score"),  # score, price, date, margin
    db: Session = Depends(get_db),
):
    query = db.query(Listing).filter(Listing.is_active == True)

    if min_score is not None:
        query = query.filter(Listing.opportunity_score >= min_score)
    if max_price is not None:
        query = query.filter(Listing.price <= max_price)
    if min_year is not None:
        query = query.filter(Listing.year >= min_year)
    if max_km is not None:
        query = query.filter(Listing.mileage <= max_km)
    if brand:
        query = query.filter(func.lower(Listing.brand) == brand.lower())
    if model:
        query = query.filter(func.lower(Listing.model).contains(model.lower()))
    if fuel_type:
        query = query.filter(func.lower(Listing.fuel_type) == fuel_type.lower())
    if is_saved is not None:
        query = query.filter(Listing.is_saved == is_saved)
    if profile_id is not None:
        query = query.filter(Listing.search_profile_id == profile_id)

    # Tri
    sort_map = {
        "score": desc(Listing.opportunity_score),
        "price": Listing.price,
        "date": desc(Listing.published_at),
        "margin": desc(Listing.potential_margin),
    }
    query = query.order_by(sort_map.get(sort_by, desc(Listing.opportunity_score)))

    total = query.count()
    listings = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "listings": [_serialize_listing(l) for l in listings],
    }


@app.get("/api/listings/best-deals")
async def best_deals(limit: int = Query(10, le=50), db: Session = Depends(get_db)):
    """Top N meilleures affaires."""
    listings = (
        db.query(Listing)
        .filter(
            and_(
                Listing.is_active == True,
                Listing.opportunity_score >= 60,
            )
        )
        .order_by(desc(Listing.opportunity_score))
        .limit(limit)
        .all()
    )
    return [_serialize_listing(l) for l in listings]


@app.get("/api/listings/new")
async def new_listings(hours: int = Query(24), db: Session = Depends(get_db)):
    """Nouvelles annonces dans les dernières X heures."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    listings = (
        db.query(Listing)
        .filter(and_(Listing.is_active == True, Listing.scraped_at >= cutoff))
        .order_by(desc(Listing.scraped_at))
        .limit(50)
        .all()
    )
    return [_serialize_listing(l) for l in listings]


@app.get("/api/listings/{listing_id}")
async def get_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce non trouvée")
    data = _serialize_listing(listing)
    # Ajouter l'historique des prix
    history = db.query(PriceHistory).filter(PriceHistory.listing_id == listing_id).all()
    data["price_history"] = [{"price": h.price, "date": h.recorded_at.isoformat()} for h in history]
    return data


@app.patch("/api/listings/{listing_id}")
async def update_listing(
    listing_id: int, data: ListingUpdate, db: Session = Depends(get_db)
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce non trouvée")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(listing, key, value)
    db.commit()
    return {"message": "Annonce mise à jour"}


# ─────────────────────────────────────────────
# API - Statistiques & Dashboard
# ─────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Statistiques générales pour le dashboard."""
    total_listings = db.query(func.count(Listing.id)).filter(Listing.is_active == True).scalar()
    total_saved = db.query(func.count(Listing.id)).filter(Listing.is_saved == True).scalar()

    best_score = db.query(func.max(Listing.opportunity_score)).filter(Listing.is_active == True).scalar()
    avg_price = db.query(func.avg(Listing.price)).filter(Listing.is_active == True).scalar()

    from datetime import timedelta
    cutoff_24h = datetime.utcnow() - timedelta(hours=24)
    new_24h = db.query(func.count(Listing.id)).filter(
        and_(Listing.is_active == True, Listing.scraped_at >= cutoff_24h)
    ).scalar()

    good_deals = db.query(func.count(Listing.id)).filter(
        and_(Listing.is_active == True, Listing.opportunity_score >= 70)
    ).scalar()

    last_run = db.query(ScrapingRun).order_by(desc(ScrapingRun.started_at)).first()

    return {
        "total_listings": total_listings,
        "total_saved": total_saved,
        "new_24h": new_24h,
        "good_deals": good_deals,
        "best_score": best_score,
        "avg_price": int(avg_price) if avg_price else None,
        "last_scrape": {
            "started_at": last_run.started_at.isoformat() if last_run else None,
            "status": last_run.status if last_run else None,
            "listings_found": last_run.listings_found if last_run else 0,
            "listings_new": last_run.listings_new if last_run else 0,
        } if last_run else None,
    }


@app.get("/api/market/{brand}/{model}")
async def market_data(
    brand: str, model: str,
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Données marché pour un modèle."""
    query = db.query(MarketData).filter(
        and_(
            func.lower(MarketData.brand) == brand.lower(),
            func.lower(MarketData.model) == model.lower(),
        )
    )
    if year:
        query = query.filter(MarketData.year == year)
    data = query.all()
    return [
        {
            "year": d.year, "mileage_range": d.mileage_range,
            "avg_price": d.avg_price, "min_price": d.min_price,
            "max_price": d.max_price, "sample_count": d.sample_count,
        }
        for d in data
    ]


# ─────────────────────────────────────────────
# API - Contrôle scraping
# ─────────────────────────────────────────────

@app.post("/api/scrape/start")
async def trigger_scrape():
    """Lancer manuellement un cycle de scraping."""
    asyncio.create_task(run_scraping_cycle())
    return {"message": "Cycle de scraping lancé"}


@app.get("/api/scrape/status")
async def scrape_status(db: Session = Depends(get_db)):
    """Statut des derniers cycles de scraping."""
    runs = db.query(ScrapingRun).order_by(desc(ScrapingRun.started_at)).limit(10).all()
    return [
        {
            "id": r.id, "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status, "listings_found": r.listings_found,
            "listings_new": r.listings_new, "listings_updated": r.listings_updated,
            "error": r.error_message,
        }
        for r in runs
    ]


@app.get("/api/scrape/next-run")
async def next_run():
    """Prochaine exécution planifiée."""
    job = scheduler.get_job("scraping_cycle")
    if job and job.next_run_time:
        return {"next_run": job.next_run_time.isoformat()}
    return {"next_run": None}


# ─────────────────────────────────────────────
# SSE - Notifications en temps réel
# ─────────────────────────────────────────────

alert_queue: asyncio.Queue = asyncio.Queue()


@app.get("/api/alerts/stream")
async def alert_stream(request: Request):
    """
    Server-Sent Events pour notifications navigateur en temps réel.
    """
    async def event_generator():
        yield "data: {\"type\": \"connected\"}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(alert_queue.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"  # Keepalive

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _serialize_listing(l: Listing) -> dict:
    return {
        "id": l.id,
        "leboncoin_id": l.leboncoin_id,
        "title": l.title,
        "url": l.url,
        "price": l.price,
        "price_is_negotiable": l.price_is_negotiable,
        "thumbnail_url": l.thumbnail_url,
        "description": l.description,
        "published_at": l.published_at.isoformat() if l.published_at else None,
        "scraped_at": l.scraped_at.isoformat() if l.scraped_at else None,
        "brand": l.brand,
        "model": l.model,
        "year": l.year,
        "mileage": l.mileage,
        "fuel_type": l.fuel_type,
        "transmission": l.transmission,
        "color": l.color,
        "owners_count": l.owners_count,
        "technical_control": l.technical_control,
        "first_hand": l.first_hand,
        "city": l.city,
        "department": l.department,
        "postal_code": l.postal_code,
        "seller_type": l.seller_type,
        "opportunity_score": l.opportunity_score,
        "price_score": l.price_score,
        "quality_score": l.quality_score,
        "urgency_score": l.urgency_score,
        "market_avg_price": l.market_avg_price,
        "price_deviation_pct": l.price_deviation_pct,
        "estimated_resale_price": l.estimated_resale_price,
        "potential_margin": l.potential_margin,
        "potential_margin_pct": l.potential_margin_pct,
        "score_details": l.score_details,
        "is_saved": l.is_saved,
        "is_contacted": l.is_contacted,
        "is_purchased": l.is_purchased,
        "user_note": l.user_note,
        "alert_sent": l.alert_sent,
    }
