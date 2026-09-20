import os
from datetime import datetime, timedelta
import requests
import feedparser

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PAIS = "ES"
IDIOMA = "es"

ayer = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

url_noticias = (
    "https://news.google.com/rss/search?"
    f"q=when:1d&hl={IDIOMA}&gl={PAIS}&ceid={PAIS}:{IDIOMA}"
)

feed = feedparser.parse(url_noticias)

if not feed.entries:
    texto = f"No encontré noticias relevantes de {ayer}."
else:
    lineas = [f"Noticias más relevantes de {ayer}\n"]
    for i, noticia in enumerate(feed.entries[:10], start=1):
        titulo = noticia.get("title", "Sin título")
        enlace = noticia.get("link", "")
        lineas.append(f"{i}. {titulo}\n{enlace}\n")
    texto = "\n".join(lineas)

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

for inicio in range(0, len(texto), 3500):
    requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": texto[inicio:inicio + 3500]},
        timeout=30,
    ).raise_for_status()
