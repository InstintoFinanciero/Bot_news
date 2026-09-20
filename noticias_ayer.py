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

MAX_NOTICIAS = 10
HORAS = 36

FEEDS = [
    "https://news.google.com/rss/search?q=(Fed+OR+BCE+OR+ECB+OR+bitcoin+OR+crypto+OR+inflation+OR+%22interest+rates%22+OR+markets)+when:1d&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(Fed+OR+BCE+OR+bitcoin+OR+criptomonedas+OR+inflaci%C3%B3n+OR+%22tipos+de+inter%C3%A9s%22)+when:1d&hl=es&gl=US&ceid=US:es",
    "https://decrypt.co/feed",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://news.google.com/rss/search?q=site:cronista.com+OR+site:ambito.com+OR+site:infobae.com+(d%C3%B3lar+OR+inflaci%C3%B3n+OR+BCRA+OR+tasas+OR+mercado+OR+bitcoin)+when:1d&hl=es-419&gl=AR&ceid=AR:es-419",
    "https://news.google.com/rss/search?q=site:investing.com+(Fed+OR+bitcoin+OR+rates+OR+inflation+OR+markets)+when:1d&hl=es&gl=US&ceid=US:es",
]

FUENTES_OK = (
    "investing.com",
    "decrypt.co",
    "coindesk.com",
    "cointelegraph.com",
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "cnbc.com",
    "expansion.com",
    "eleconomista.es",
    "cronista.com",
    "ambito.com",
    "infobae.com",
    "lanacion.com.ar",
    "criptonoticias.com",
)

TEMA_OK = (
    "fed", "fomc", "bce", "ecb", "tasa", "tasas", "interés", "interes",
    "inflation", "inflación", "inflacion", "bitcoin", "ethereum",
    "crypto", "cripto", "mercado", "bolsa", "wall street", "bonos",
    "tesoro", "dólar", "dolar", "bcra", "peso", "argentina", "oil",
    "petróleo", "oro", "gold", "acciones", "banks", "bancos",
)

BASURA = (
    "análisis técnico", "analisis tecnico", "gráfico", "grafico",
    "foro ", "0p000", "hedged", "perpetual", "ultra short",
    "focused large cap", "swan ultra",
)

ARGENTINA = (
    "argentina", "argentin", "peso", "dólar blue", "dolar blue",
    "bcra", "milei", "caputo", "buenos aires", "cronista",
    "ámbito", "ambito", "infobae",
)


def texto_limpio(html):
    if not html:
        return ""
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = unescape(texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def titulo_limpio(titulo):
    titulo = re.sub(r"\s+-\s+Investing\.com.*$", "", titulo)
    titulo = re.sub(r"\s+-\s+[A-ZÁÉÍÓÚÑ][^-]{0,40}$", "", titulo)
    return titulo.strip()


def resumen_limpio(titulo, resumen):
    if not resumen:
        return "Abrí el enlace para ver el detalle."
    if resumen.lower().startswith(titulo.lower()[:40]):
        resto = resumen[len(titulo):].strip(" -:.")
        resumen = resto or resumen
    if len(resumen) > 220:
        resumen = resumen[:217].rsplit(" ", 1)[0] + "..."
    return resumen


def es_basura(titulo):
    t = titulo.lower()
    return any(p in t for p in BASURA)


def es_relevante(titulo, resumen, enlace):
    blob = f"{titulo} {resumen} {enlace}".lower()
    if not any(f in blob for f in FUENTES_OK) and not any(p in blob for p in TEMA_OK):
        return False
    return any(p in blob for p in TEMA_OK) or any(f in blob for f in FUENTES_OK)


def es_argentina(titulo, resumen, enlace):
    blob = f"{titulo} {resumen} {enlace}".lower()
    return any(p in blob for p in ARGENTINA)


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


def acortar(url):
    url = enlace_real(url)
    try:
        r = requests.get(
            "https://is.gd/create.php",
            params={"format": "simple", "url": url},
            timeout=15,
        )
        if r.ok and r.text.startswith("http") and "news.google.com" not in r.text:
            return r.text.strip()
    except Exception:
        pass
    try:
        r = requests.get(
            "https://tinyurl.com/api-create.php",
            params={"url": url},
            timeout=15,
        )
        if r.ok and r.text.startswith("http") and "news.google.com" not in r.text:
            return r.text.strip()
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
            enlace = (entrada.get("link") or "").strip()
            resumen = texto_limpio(entrada.get("summary") or entrada.get("description") or "")
            resumen = resumen_limpio(titulo, resumen)

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
                "resumen": resumen,
                "enlace": enlace,
                "argentina": es_argentina(titulo, resumen, enlace),
            })

    ar = [n for n in noticias if n["argentina"]]
    resto = [n for n in noticias if not n["argentina"]]
    return (ar[:4] + resto)[:MAX_NOTICIAS]


def armar_mensaje(noticias):
    lineas = ["📈 Bienvenido a las noticias de hoy:\n"]
    for i, n in enumerate(noticias, start=1):
        bandera = " 🇦🇷" if n["argentina"] else ""
        link = acortar(n["enlace"])
        lineas.append(f"{i}) {n['titulo']}{bandera}")
        lineas.append(n["resumen"])
        lineas.append(f"🔗 {link}\n")
    return "\n".join(lineas)


def enviar(texto):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for inicio in range(0, len(texto), 3500):
        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": texto[inicio:inicio + 3500],
                "disable_web_page_preview": True,
            },
            timeout=30,
        ).raise_for_status()


if __name__ == "__main__":
    noticias = recoger()
    if not noticias:
        enviar("📈 Bienvenido a las noticias de hoy:\n\nHoy no encontré piezas financieras o cripto lo bastante relevantes.")
    else:
        enviar(armar_mensaje(noticias))
