"""
Scraper Leboncoin avec Playwright.

Stratégies anti-blocage :
- Rotation d'user-agents réalistes
- Délais aléatoires entre actions (comportement humain)
- Mouvements de souris simulés
- Gestion des CAPTCHAs (pause + notification)
- Rotation de proxies (optionnel)
- Headers HTTP complets
"""
import asyncio
import random
import re
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode, quote

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)


# Pool d'user-agents Chrome récents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:122.0) Gecko/20100101 Firefox/122.0",
]

# Résolutions d'écran courantes
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]

# Mots-clés d'urgence qui indiquent un vendeur pressé (score +)
URGENCY_KEYWORDS = [
    "urgent", "rapidement", "vite", "déménagement", "départ", "retraite",
    "cause retraite", "cause déménagement", "cause maladie", "nécessité",
    "obligation", "départ à l'étranger", "quitte", "libère", "pressé",
    "prix ferme", "à vendre de suite", "besoin rapide"
]

# Mots-clés qualité positive
QUALITY_KEYWORDS_POSITIVE = [
    "première main", "1ère main", "1 propriétaire", "carnet d'entretien",
    "suivi concessionnaire", "révisé", "contrôle technique ok", "CT ok",
    "sans accident", "non fumeur", "garage", "jamais accidenté"
]

# Mots-clés négatifs (problèmes)
QUALITY_KEYWORDS_NEGATIVE = [
    "accidenté", "à réparer", "pour pièce", "pièces", "roulant",
    "moteur hs", "boîte hs", "à réviser", "problème", "défaut"
]


class LeboncoinScraper:
    """Scraper Leboncoin avec simulation de comportement humain."""

    BASE_URL = "https://www.leboncoin.fr"
    SEARCH_URL = "https://www.leboncoin.fr/voitures/offres"

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def start(self):
        """Démarrer le navigateur Playwright."""
        self._playwright = await async_playwright().start()
        proxy_config = None
        if settings.PROXY_LIST:
            proxy = random.choice(settings.PROXY_LIST)
            proxy_config = {"server": proxy}

        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--window-size=1920,1080",
            ],
            proxy=proxy_config,
        )
        viewport = random.choice(VIEWPORTS)
        ua = random.choice(USER_AGENTS)

        self.context = await self.browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            extra_http_headers={
                "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        # Masquer que c'est Playwright
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR', 'fr'] });
            window.chrome = { runtime: {} };
        """)

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, '_playwright'):
            await self._playwright.stop()

    async def _human_delay(self, min_s: float = None, max_s: float = None):
        """Attendre un délai aléatoire pour simuler un humain."""
        min_s = min_s or settings.SCRAPE_DELAY_MIN
        max_s = max_s or settings.SCRAPE_DELAY_MAX
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _simulate_scroll(self, page: Page):
        """Simuler un scroll humain sur la page."""
        total_height = await page.evaluate("document.body.scrollHeight")
        current_pos = 0
        while current_pos < total_height:
            scroll_step = random.randint(200, 600)
            current_pos += scroll_step
            await page.evaluate(f"window.scrollTo(0, {current_pos})")
            await asyncio.sleep(random.uniform(0.1, 0.4))

    async def _accept_cookies(self, page: Page):
        """Accepter la bannière cookies si présente."""
        try:
            btn = page.locator("[data-testid='Didomi-notice-agree-button'], #didomi-notice-agree-button, button:has-text('Accepter')")
            if await btn.count() > 0:
                await btn.first.click()
                await self._human_delay(1, 2)
        except Exception:
            pass

    def _build_search_url(self, profile: dict, page_num: int = 1) -> str:
        """
        Construire l'URL de recherche Leboncoin.
        Leboncoin utilise des paramètres dans l'URL pour les filtres.
        """
        params = {}

        if profile.get("brand"):
            params["brand"] = profile["brand"].lower()
        if profile.get("model"):
            params["model"] = profile["model"].lower()
        if profile.get("min_price"):
            params["price"] = f"{profile['min_price']}-{profile.get('max_price', '')}"
        elif profile.get("max_price"):
            params["price"] = f"-{profile['max_price']}"
        if profile.get("min_year") or profile.get("max_year"):
            min_y = profile.get("min_year", "")
            max_y = profile.get("max_year", "")
            params["regdate"] = f"{min_y}-{max_y}"
        if profile.get("max_km"):
            params["mileage"] = f"-{profile['max_km']}"
        if profile.get("fuel_type"):
            fuel_map = {
                "essence": "1", "diesel": "2", "hybride": "3",
                "electrique": "5", "gpl": "4"
            }
            params["fuel"] = fuel_map.get(profile["fuel_type"].lower(), "")
        if profile.get("transmission"):
            params["gearbox"] = "1" if "auto" in profile["transmission"].lower() else "2"
        if profile.get("location_city"):
            params["location"] = quote(profile["location_city"])
        if profile.get("location_radius_km"):
            params["radius"] = str(profile["location_radius_km"])

        params["sort"] = "time"  # Tri par date (plus récent en premier)
        params["owner_type"] = "private"  # Particuliers seulement (modifiable)

        if page_num > 1:
            params["page"] = str(page_num)

        url = self.SEARCH_URL
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items() if v)
        return url

    async def scrape_search_page(self, profile: dict, max_pages: int = 5) -> list[dict]:
        """
        Scraper une page de résultats de recherche.
        Retourne une liste de dictionnaires d'annonces.
        """
        all_listings = []
        page = await self.context.new_page()

        try:
            for page_num in range(1, max_pages + 1):
                url = self._build_search_url(profile, page_num)
                logger.info(f"Scraping page {page_num}: {url}")

                await page.goto(url, wait_until="networkidle", timeout=30000)
                await self._accept_cookies(page)
                await self._human_delay()
                await self._simulate_scroll(page)

                # Vérifier CAPTCHA
                if await self._check_captcha(page):
                    logger.warning("CAPTCHA détecté ! Pause de 60 secondes...")
                    await asyncio.sleep(60)
                    break

                # Extraire les annonces
                html = await page.content()
                listings = self._parse_search_results(html)

                if not listings:
                    logger.info(f"Plus d'annonces à la page {page_num}")
                    break

                all_listings.extend(listings)
                logger.info(f"Page {page_num}: {len(listings)} annonces trouvées")

                if len(all_listings) >= settings.MAX_LISTINGS_PER_CYCLE:
                    break

                # Délai entre pages
                await self._human_delay(3, 7)

        except Exception as e:
            logger.error(f"Erreur scraping: {e}")
        finally:
            await page.close()

        return all_listings[:settings.MAX_LISTINGS_PER_CYCLE]

    async def scrape_listing_detail(self, url: str) -> dict:
        """
        Scraper le détail d'une annonce pour obtenir plus d'informations.
        """
        page = await self.context.new_page()
        detail = {}

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await self._human_delay(1, 3)
            html = await page.content()
            detail = self._parse_listing_detail(html)
        except Exception as e:
            logger.error(f"Erreur scraping détail {url}: {e}")
        finally:
            await page.close()

        return detail

    async def _check_captcha(self, page: Page) -> bool:
        """Vérifier si un CAPTCHA est présent."""
        captcha_selectors = [
            "iframe[src*='captcha']",
            ".captcha",
            "#captcha",
            "iframe[src*='recaptcha']",
            "[data-testid='captcha']",
        ]
        for sel in captcha_selectors:
            if await page.locator(sel).count() > 0:
                return True
        return False

    def _parse_search_results(self, html: str) -> list[dict]:
        """
        Parser le HTML des résultats de recherche.
        Leboncoin charge les données via un JSON embarqué dans la page (Next.js).
        """
        listings = []

        # Méthode 1 : Extraire le JSON __NEXT_DATA__ (méthode principale)
        try:
            import json
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                props = data.get("props", {}).get("pageProps", {})
                # Chercher les annonces dans la structure JSON
                ads = props.get("searchData", {}).get("ads", []) or \
                      props.get("ads", []) or \
                      props.get("data", {}).get("ads", [])

                for ad in ads:
                    listing = self._normalize_ad_from_json(ad)
                    if listing:
                        listings.append(listing)
                if listings:
                    return listings
        except Exception as e:
            logger.debug(f"JSON parse failed: {e}")

        # Méthode 2 : Parsing HTML direct (fallback)
        try:
            soup = BeautifulSoup(html, "html.parser")
            # Chercher les cartes d'annonces
            cards = soup.find_all("article", {"data-qa-id": re.compile(r"aditem_container")}) or \
                    soup.find_all("li", class_=re.compile(r"styles_adCard")) or \
                    soup.find_all("div", class_=re.compile(r"ad-card"))

            for card in cards:
                listing = self._parse_card_html(card)
                if listing:
                    listings.append(listing)
        except Exception as e:
            logger.debug(f"HTML parse failed: {e}")

        return listings

    def _normalize_ad_from_json(self, ad: dict) -> Optional[dict]:
        """Normaliser une annonce depuis le JSON Next.js de Leboncoin."""
        try:
            attributes = {attr["key"]: attr.get("value_label", attr.get("value")) for attr in ad.get("attributes", [])}

            price = None
            if ad.get("price"):
                price = ad["price"][0] if isinstance(ad["price"], list) else ad["price"]

            location = ad.get("location", {})
            images = ad.get("images", {})
            thumb = None
            if images.get("thumb_url"):
                thumb = images["thumb_url"]
            elif images.get("urls") and images["urls"]:
                thumb = images["urls"][0]

            published_at = None
            if ad.get("first_publication_date"):
                try:
                    published_at = datetime.fromisoformat(ad["first_publication_date"].replace("Z", "+00:00"))
                except Exception:
                    pass

            return {
                "leboncoin_id": str(ad.get("list_id", "")),
                "title": ad.get("subject", ""),
                "url": f"https://www.leboncoin.fr{ad.get('url', '')}",
                "price": int(price) if price else None,
                "thumbnail_url": thumb,
                "description": ad.get("body", ""),
                "published_at": published_at,
                "brand": attributes.get("brand", ""),
                "model": attributes.get("model", ""),
                "year": self._safe_int(attributes.get("regdate")),
                "mileage": self._safe_int(attributes.get("mileage")),
                "fuel_type": attributes.get("fuel", ""),
                "transmission": attributes.get("gearbox", ""),
                "doors": self._safe_int(attributes.get("doors")),
                "seats": self._safe_int(attributes.get("seats")),
                "color": attributes.get("color", ""),
                "owners_count": self._safe_int(attributes.get("previous_owners")),
                "technical_control": attributes.get("vehicle_technical_inspection") == "1",
                "first_hand": attributes.get("condition") == "1",
                "city": location.get("city", ""),
                "department": location.get("department_id", ""),
                "postal_code": location.get("zipcode", ""),
                "latitude": location.get("lat"),
                "longitude": location.get("lng"),
                "seller_type": ad.get("owner", {}).get("type", ""),
                "seller_name": ad.get("owner", {}).get("name", ""),
                "price_is_negotiable": ad.get("price_cents_negotiable", False),
            }
        except Exception as e:
            logger.debug(f"Error normalizing ad: {e}")
            return None

    def _parse_card_html(self, card) -> Optional[dict]:
        """Parser une carte d'annonce en HTML (fallback)."""
        try:
            title_el = card.find(["h2", "h3", "p"], class_=re.compile(r"title|subject"))
            price_el = card.find(["span", "p"], class_=re.compile(r"price"))
            link_el = card.find("a", href=True)
            img_el = card.find("img")

            title = title_el.get_text(strip=True) if title_el else ""
            price_text = price_el.get_text(strip=True) if price_el else ""
            price = self._extract_price(price_text)
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = self.BASE_URL + url
            thumbnail = img_el.get("src", img_el.get("data-src", "")) if img_el else ""

            # ID depuis l'URL
            lid_match = re.search(r"/(\d+)\.htm", url)
            leboncoin_id = lid_match.group(1) if lid_match else ""

            return {
                "leboncoin_id": leboncoin_id,
                "title": title,
                "url": url,
                "price": price,
                "thumbnail_url": thumbnail,
            }
        except Exception:
            return None

    def _parse_listing_detail(self, html: str) -> dict:
        """Parser le détail d'une annonce."""
        detail = {}
        try:
            import json
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                ad = data.get("props", {}).get("pageProps", {}).get("ad", {})
                if ad:
                    detail = self._normalize_ad_from_json(ad) or {}
        except Exception as e:
            logger.debug(f"Detail parse error: {e}")
        return detail

    def _extract_price(self, text: str) -> Optional[int]:
        """Extraire un prix depuis une chaîne de texte."""
        cleaned = re.sub(r"[^\d]", "", text)
        return int(cleaned) if cleaned else None

    def _safe_int(self, value) -> Optional[int]:
        """Convertir en int sans lever d'exception."""
        try:
            return int(str(value).replace(" ", "").replace("km", "").replace("€", ""))
        except (ValueError, TypeError):
            return None


async def run_scrape(profile: dict) -> list[dict]:
    """Point d'entrée pour lancer un scraping."""
    async with LeboncoinScraper() as scraper:
        return await scraper.scrape_search_page(profile)
