import os
import re
import base64
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import requests
import feedparser

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_NOTICIAS = 5
HORAS = 36

FEEDS = [
    "https://news.google.com/rss/search?q=(Fed+OR+FOMC+OR+Powell+OR+gold+OR+oro+OR+bitcoin+OR+BTC+OR+inflation+OR+%22interest+rates%22)+when:1d&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(Fed+OR+Powell+OR+oro+OR+bitcoin+OR+inflaci%C3%B3n+OR+%22tipos+de+inter%C3%A9s%22)+when:1d&hl=es&gl=US&ceid=US:es",
    "https://decrypt.co/feed",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://news.google.com/rss/search?q=site:cronista.com+OR+site:ambito.com+OR+site:infobae.com+(Fed+OR+oro+OR+bitcoin+OR+d%C3%B3lar+OR+BCRA+OR+tasas)+when:1d&hl=es-419&gl=AR&ceid=AR:es-419",
    "https://news.google.com/rss/search?q=site:investing.com+(Fed+OR+gold+OR+oro+OR+bitcoin+OR+rates+OR+inflation)+when:1d&hl=es&gl=US&ceid=US:es",
]

FUENTES_OK = (
    "investing.com", "decrypt.co", "coindesk.com", "cointelegraph.com",
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com",
    "expansion.com", "eleconomista.es", "cronista.com", "ambito.com",
    "infobae.com", "lanacion.com.ar", "criptonoticias.com",
)

TEMA_OK = (
    "fed", "fomc", "powell", "bce", "ecb", "tasa", "tasas", "interés", "interes",
    "inflation", "inflación", "inflacion", "bitcoin", "btc", "ethereum",
    "crypto", "cripto", "mercado", "bolsa", "wall street", "bonos",
    "tesoro", "dólar", "dolar", "bcra", "peso", "oil", "petróleo",
    "oro", "gold", "xau",
)

BASURA = (
    "análisis técnico", "analisis tecnico", "gráfico", "grafico",
    "foro ", "0p000", "hedged", "perpetual", "ultra short",
    "focused large cap", "swan ultra", "florida bar", "judgments",
    "decrees", "receta", "horóscopo", "horoscopo",
)

PRIORIDAD = {
    "fed": 100, "federal reserve": 100, "fomc": 95, "powell": 95,
    "oro": 90, "gold": 90, "xau": 90,
    "bitcoin": 88, "btc": 88,
    "tasa": 70, "tasas": 70, "interés": 70, "interes": 70,
    "inflation": 65, "inflación": 65, "inflacion": 65,
    "dólar": 50, "dolar": 50, "cripto": 40, "crypto": 40,
}


def texto_limpio(html):
    if not html:
        return ""
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = unescape(texto)
    return re.sub(r"\s+", " ", texto).strip()


def titulo_limpio(titulo):
    titulo = re.sub(r"\s+-\s+Investing\.com.*$", "", titulo)
    titulo = re.sub(r"\s+-\s+[A-ZÁÉÍÓÚÑ][^-]{0,40}$", "", titulo)
    return titulo.strip()


def fuente_de(titulo, enlace):
    blob = f"{titulo} {enlace}".lower()
    for f in FUENTES_OK:
        if f in blob:
            return f
    return ""


def es_basura(titulo):
    t = titulo.lower()
    return any(p in t for p in BASURA)


def es_relevante(titulo, resumen, enlace):
    blob = f"{titulo} {resumen} {enlace}".lower()
    return any(p in blob for p in TEMA_OK)


def puntaje(titulo, resumen, enlace):
    blob = f"{titulo} {resumen} {enlace}".lower()
    pts = [v for k, v in PRIORIDAD.items() if k in blob]
    return max(pts) if pts else 10


def grupo(titulo, resumen):
    t = f"{titulo} {resumen}".lower()
    if any(k in t for k in ("fed", "fomc", "powell", "tasa", "tasas", "inflation", "inflación", "inflacion")):
        return "🏦 FED / Macro"
    if any(k in t for k in ("oro", "gold", "xau")):
        return "🥇 Oro"
    if any(k in t for k in ("bitcoin", "btc", "cripto", "crypto", "ethereum")):
        return "🪙 Cripto"
    return "📌 Extra"


def fecha_ok(entrada):
    for campo in ("published", "updated"):
        valor = entrada.get(campo)
        if not valor:
            continue
        try:
            return parsedate_to_datetime(valor).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def enlace_real(url):
    if "news.google.com" not in url:
        return url
    match = re.search(r"/articles/([A-Za-z0-9_\-]+)", url)
    if not match:
        return url
    raw = match.group(1)
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw).decode("latin-1", errors="ignore")
        encontrado = re.search(r"https?://[^ \x00-\x1f]+", decoded)
        if encontrado:
            return encontrado.group(0).split("\x00")[0]
    except Exception:
        pass
    return url


def recoger():
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS)
    vistas = set()
    noticias = []

    for url in FEEDS:
        feed = feedparser.parse(url)
        for entrada in feed.entries:
            titulo = titulo_limpio(entrada.get("title") or "Sin título")
            enlace = enlace_real((entrada.get("link") or "").strip())
            resumen = texto_limpio(entrada.get("summary") or entrada.get("description") or "")

            if not enlace or es_basura(titulo):
                continue
            if fecha_ok(entrada) < limite:
                continue
            if not es_relevante(titulo, resumen, enlace):
                continue

            clave = titulo.lower()
            if clave in vistas:
                continue
            vistas.add(clave)

            noticias.append({
                "titulo": titulo,
                "enlace": enlace,
                "fuente": fuente_de(titulo, enlace),
                "grupo": grupo(titulo, resumen),
                "pts": puntaje(titulo, resumen, enlace),
            })

    noticias.sort(key=lambda n: n["pts"], reverse=True)
    return noticias[:MAX_NOTICIAS]


def armar_mensaje(noticias):
    dias = {
        "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
        "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado",
        "Sunday": "domingo",
    }
    hoy = datetime.now()
    dia = dias.get(hoy.strftime("%A"), hoy.strftime("%A"))
    lineas = [f"📰 <b>Noticias</b> · {dia} {hoy:%d/%m}", ""]

    orden = ["🏦 FED / Macro", "🥇 Oro", "🪙 Cripto", "📌 Extra"]
    nro = 1
    for g in orden:
        items = [x for x in noticias if x["grupo"] == g]
        if not items:
            continue
        lineas.append(f"<b>{g}</b>")
        for it in items:
            lineas.append(f'{nro}. <a href="{it["enlace"]}">{it["titulo"]}</a>')
            if it["fuente"]:
                lineas.append(f"   {it['fuente']}")
            nro += 1
        lineas.append("")
    return "\n".join(lineas).strip()


def enviar(texto):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    ).raise_for_status()


if __name__ == "__main__":
    noticias = recoger()
    if not noticias:
        enviar("📰 <b>Noticias</b>\n\nHoy no hubo piezas fuertes de FED, oro o Bitcoin.")
    else:
        enviar(armar_mensaje(noticias))
