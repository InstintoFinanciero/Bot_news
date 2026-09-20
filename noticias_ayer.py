import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import requests
import feedparser

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_NOTICIAS = 12
HORAS = 36

FUENTES_PERMITIDAS = (
    "investing.com",
    "decrypt.co",
    "coindesk.com",
    "cointelegraph.com",
    "reuters.com",
    "bloomberg.com",
    "expansion.com",
    "eleconomista.es",
    "ft.com",
    "wsj.com",
    "criptonoticias.com",
)

PALABRAS = (
    "tipo de interés",
    "tasas de interés",
    "tipos de interés",
    "interest rate",
    "fed",
    "fomc",
    "bce",
    "ecb",
    "inflación",
    "inflation",
    "bitcoin",
    "ethereum",
    "crypto",
    "cripto",
    "criptomoneda",
    "mercado",
    "bolsa",
    "acciones",
    "tesoro",
    "bonos",
    "wall street",
)

FEEDS = [
    "https://news.google.com/rss/search?q=site:investing.com+when:1d&hl=es&gl=ES&ceid=ES:es",
    "https://news.google.com/rss/search?q=site:decrypt.co+when:1d&hl=es&gl=US&ceid=US:es",
    "https://news.google.com/rss/search?q=(Fed+OR+BCE+OR+%22tipos+de+interes%22+OR+bitcoin+OR+criptomonedas)+when:1d&hl=es&gl=ES&ceid=ES:es",
    "https://decrypt.co/feed",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

def es_fuente_ok(enlace, titulo):
    texto = f"{enlace} {titulo}".lower()
    return any(fuente in texto for fuente in FUENTES_PERMITIDAS)

def es_tema_ok(titulo):
    t = titulo.lower()
    return any(p in t for p in PALABRAS)

def fecha_noticia(entrada):
    for campo in ("published", "updated"):
        valor = entrada.get(campo)
        if valor:
            try:
                return parsedate_to_datetime(valor).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)

def recoger():
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS)
    vistas = set()
    noticias = []

    for url in FEEDS:
        feed = feedparser.parse(url)
        for entrada in feed.entries:
            titulo = (entrada.get("title") or "Sin título").strip()
            enlace = (entrada.get("link") or "").strip()
            if not enlace:
                continue

            clave = titulo.lower()
            if clave in vistas:
                continue
            if fecha_noticia(entrada) < limite:
                continue
            if not es_fuente_ok(enlace, titulo) and not es_tema_ok(titulo):
                continue

            vistas.add(clave)
            noticias.append((titulo, enlace))

    return noticias[:MAX_NOTICIAS]

def enviar(texto):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for inicio in range(0, len(texto), 3500):
        requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": texto[inicio:inicio + 3500]},
            timeout=30,
        ).raise_for_status()

if __name__ == "__main__":
    ayer = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    noticias = recoger()

    if not noticias:
        enviar(f"No encontré noticias financieras/cripto de {ayer}.")
    else:
        lineas = [f"Resumen financiero de {ayer}\n"]
        for i, (titulo, enlace) in enumerate(noticias, start=1):
            lineas.append(f"{i}. {titulo}\n{enlace}\n")
        enviar("\n".join(lineas))
