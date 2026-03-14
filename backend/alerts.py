"""
Système d'alertes multi-canal.
Supporte : Email (SMTP), Telegram, notifications navigateur (via SSE).
"""
import smtplib
import logging
import httpx
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


def _build_listing_summary(listing) -> dict:
    """Construire un résumé d'annonce pour les alertes."""
    price_info = ""
    if listing.price_deviation_pct and listing.price_deviation_pct < 0:
        price_info = f" ({abs(listing.price_deviation_pct):.0f}% sous la moyenne)"

    return {
        "title": listing.title or "Annonce sans titre",
        "price": f"{listing.price:,}€".replace(",", " ") if listing.price else "Prix NC",
        "mileage": f"{listing.mileage:,} km".replace(",", " ") if listing.mileage else "km NC",
        "year": str(listing.year) if listing.year else "Année NC",
        "city": listing.city or "Localisation NC",
        "score": listing.opportunity_score or 0,
        "url": listing.url or "#",
        "price_info": price_info,
        "margin": f"{listing.potential_margin:,}€".replace(",", " ") if listing.potential_margin else "NC",
        "margin_pct": f"{listing.potential_margin_pct:.0f}%" if listing.potential_margin_pct else "NC",
    }


def send_email_alert(listing) -> bool:
    """
    Envoyer une alerte email pour une bonne affaire.
    Utilise le serveur SMTP configuré dans .env
    """
    if not all([settings.SMTP_USER, settings.SMTP_PASSWORD, settings.ALERT_EMAIL_TO]):
        logger.debug("Email non configuré, alerte ignorée")
        return False

    summary = _build_listing_summary(listing)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚗 Bonne affaire détectée ! Score {summary['score']}/100 - {summary['title']}"
    msg["From"] = settings.SMTP_USER
    msg["To"] = settings.ALERT_EMAIL_TO

    # Version texte
    text_body = f"""
BONNE AFFAIRE DÉTECTÉE - Score {summary['score']}/100
{'=' * 50}

Titre    : {summary['title']}
Prix     : {summary['price']}{summary['price_info']}
Km       : {summary['mileage']}
Année    : {summary['year']}
Ville    : {summary['city']}
Marge    : {summary['margin']} ({summary['margin_pct']})

Voir l'annonce : {summary['url']}
"""

    # Version HTML
    score_color = "#2ecc71" if summary["score"] >= 80 else "#f39c12" if summary["score"] >= 60 else "#e74c3c"
    html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px;">
  <div style="background: white; border-radius: 10px; padding: 25px; max-width: 600px; margin: auto; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
    <h1 style="color: #2c3e50; font-size: 20px;">🚗 Bonne affaire détectée !</h1>
    <div style="background: {score_color}; color: white; border-radius: 50%; width: 70px; height: 70px; display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: bold; margin: 15px 0;">
      {summary['score']}
    </div>
    <h2 style="color: #2c3e50;">{summary['title']}</h2>
    <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
      <tr style="background: #f8f9fa;">
        <td style="padding: 10px; font-weight: bold;">Prix</td>
        <td style="padding: 10px; color: #2ecc71; font-size: 18px;">{summary['price']} <small style="color:#666;">{summary['price_info']}</small></td>
      </tr>
      <tr>
        <td style="padding: 10px; font-weight: bold;">Kilométrage</td>
        <td style="padding: 10px;">{summary['mileage']}</td>
      </tr>
      <tr style="background: #f8f9fa;">
        <td style="padding: 10px; font-weight: bold;">Année</td>
        <td style="padding: 10px;">{summary['year']}</td>
      </tr>
      <tr>
        <td style="padding: 10px; font-weight: bold;">Ville</td>
        <td style="padding: 10px;">{summary['city']}</td>
      </tr>
      <tr style="background: #f8f9fa;">
        <td style="padding: 10px; font-weight: bold;">Marge estimée</td>
        <td style="padding: 10px; color: #2ecc71; font-weight: bold;">{summary['margin']} ({summary['margin_pct']})</td>
      </tr>
    </table>
    <a href="{summary['url']}"
       style="display: block; background: #3498db; color: white; padding: 15px; text-align: center; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; margin-top: 20px;">
       Voir l'annonce sur Leboncoin →
    </a>
  </div>
</body>
</html>
"""

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, settings.ALERT_EMAIL_TO, msg.as_string())
        logger.info(f"Email d'alerte envoyé pour {listing.leboncoin_id}")
        return True
    except Exception as e:
        logger.error(f"Erreur envoi email: {e}")
        return False


async def send_telegram_alert(listing) -> bool:
    """
    Envoyer une alerte Telegram.
    Nécessite TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env
    """
    if not all([settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID]):
        logger.debug("Telegram non configuré, alerte ignorée")
        return False

    summary = _build_listing_summary(listing)
    score_emoji = "🔥" if summary["score"] >= 80 else "⭐" if summary["score"] >= 60 else "👍"

    message = f"""{score_emoji} *BONNE AFFAIRE - Score {summary['score']}/100*

🚗 *{summary['title']}*
💰 Prix : *{summary['price']}*{summary['price_info']}
📍 {summary['city']}
📅 {summary['year']} • {summary['mileage']}
💵 Marge estimée : *{summary['margin']}* ({summary['margin_pct']})

[Voir l'annonce →]({summary['url']})"""

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        logger.info(f"Alerte Telegram envoyée pour {listing.leboncoin_id}")
        return True
    except Exception as e:
        logger.error(f"Erreur envoi Telegram: {e}")
        return False


async def send_alerts(listing, db) -> None:
    """
    Envoyer toutes les alertes configurées pour une annonce si le seuil est atteint.
    """
    if (listing.opportunity_score or 0) < settings.ALERT_SCORE_THRESHOLD:
        return
    if listing.alert_sent:
        return

    email_ok = send_email_alert(listing)
    telegram_ok = await send_telegram_alert(listing)

    if email_ok or telegram_ok:
        listing.alert_sent = True
        db.commit()
        logger.info(f"Alertes envoyées pour annonce {listing.leboncoin_id} (score: {listing.opportunity_score})")
