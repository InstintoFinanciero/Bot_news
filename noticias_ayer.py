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
MAX_POR_TEMA = 2
HORAS = 36

FEEDS = [
    "https://news.google.com/rss/search?q=(Fed+OR+FOMC+OR+Powell+OR+%22interest+rates%22+OR+inflation)+when:1d&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(gold+OR+oro+OR+XAU)+when:1d&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(bitcoin+OR+BTC)+when:1d&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(Fed+OR+Powell+OR+oro+OR+bitcoin)+when:1d&hl=es&gl=US&ceid=US:es",
    "https://decrypt.co/feed",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://news.google.com/rss/search?q=site:cronista.com+OR+site:ambito.com+OR+site:infobae.com+(Fed+OR+oro+OR+bitcoin)+when:1d&hl=es-419&gl=AR&ceid=AR:es-419",
    "https://news.google.com/rss/search?q=site:investing.com+(Fed+OR+gold+OR+oro+OR+bitcoin)+when:1d&hl=es&gl=US&ceid=US:es",
]

TEMA_OK = (
    "fed", "fomc", "powell", "tasa", "tasas", "interés", "interes",
    "inflation", "inflación", "inflacion", "bitcoin", "btc",
    "oro", "gold", "xau",
)

BASURA = (
    "análisis técnico", "analisis tecnico", "gráfico", "grafico",
    "foro ", "0p000", "hedged", "perpetual", "ultra short",
    "florida bar", "judgments", "decrees", "wallet",
    "how the fed interest rate hike will hit your wallet",
)

PRIORIDAD = {
    "fed": 100, "federal reserve": 100, "fomc": 95, "powell": 95,
    "oro": 90, "gold": 90, "xau": 90,
    "bitcoin": 88, "btc": 88,
    "tasa": 70, "tasas": 70,
    "inflation": 65, "inflación": 65, "inflacion": 65,
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


def resumen_corto(titulo, resumen):
    t = (resumen or "").strip()
    if t.lower().startswith((titulo or "").lower()[:40]):
        t = t[len(titulo):].strip(" -:.")
    t = re.sub(r"\s+", " ", t)
    if len(t) < 20:
        return "Abrí el enlace para ver el detalle."
    if len(t) > 110:
        t = t[:107].rsplit(" ", 1)[0] + "…"
    return t


def es_basura(titulo):
    return any(p in titulo.lower() for p in BASURA)


def puntaje(blob):
    pts = [v for k, v in PRIORIDAD.items() if k in blob]
    return max(pts) if pts else 0


def clasificar(titulo, resumen):
    t = f"{titulo} {resumen}".lower()
    es_oro = any(k in t for k in ("oro", "gold", "xau", "bullion"))
    es_btc = any(k in t for k in ("bitcoin", "btc"))
    es_fed = any(k in t for k in ("fed", "fomc", "powell", "federal reserve"))

    if es_oro and not es_btc:
        return "🥇 Oro"
    if es_btc and not es_oro:
        return "🪙 Bitcoin"
    if es_fed:
        return "🏦 Fed / macro"
    if es_oro:
        return "🥇 Oro"
    if es_btc:
        return "🪙 Bitcoin"
    return None


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
    por_tema = {"🏦 Fed / macro": [], "🥇 Oro": [], "🪙 Bitcoin": []}

    for url in FEEDS:
        feed = feedparser.parse(url)
        for entrada in feed.entries:
            titulo = titulo_limpio(entrada.get("title") or "Sin título")
            enlace = enlace_real((entrada.get("link") or "").strip())
            resumen = texto_limpio(entrada.get("summary") or entrada.get("description") or "")
            tema = clasificar(titulo, resumen)
            blob = f"{titulo} {resumen}".lower()

            if not enlace or not tema or es_basura(titulo):
                continue
            if fecha_ok(entrada) < limite:
                continue
            if not any(p in blob for p in TEMA_OK):
                continue

            clave = titulo.lower()
            if clave in vistas:
                continue
            vistas.add(clave)

            por_tema[tema].append({
                "titulo": titulo,
                "resumen": resumen_corto(titulo, resumen),
                "enlace": enlace,
                "tema": tema,
                "pts": puntaje(blob),
            })

    for tema in por_tema:
        por_tema[tema].sort(key=lambda n: n["pts"], reverse=True)

    elegidas = []
    # 1 de cada tema primero, para que no salgan 5 de FED
    for tema in ("🏦 Fed / macro", "🥇 Oro", "🪙 Bitcoin"):
        if por_tema[tema]:
            elegidas.append(por_tema[tema].pop(0))

    # completar hasta 5, máx 2 por tema
    resto = []
    for tema, items in por_tema.items():
        resto.extend(items)
    resto.sort(key=lambda n: n["pts"], reverse=True)

    conteo = {}
    for n in elegidas:
        conteo[n["tema"]] = conteo.get(n["tema"], 0) + 1

    for n in resto:
        if len(elegidas) >= MAX_NOTICIAS:
            break
        if conteo.get(n["tema"], 0) >= MAX_POR_TEMA:
            continue
        elegidas.append(n)
        conteo[n["tema"]] = conteo.get(n["tema"], 0) + 1

    return elegidas[:MAX_NOTICIAS]


def armar_mensaje(noticias):
    dias = {
        "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
        "Thursday": "jueves", "Friday": "viernes",
        "Saturday": "sábado", "Sunday": "domingo",
    }
    hoy = datetime.now()
    dia = dias.get(hoy.strftime("%A"), hoy.strftime("%A"))
    lineas = [f"📰 <b>Noticias</b> · {dia} {hoy:%d/%m}", ""]

    for i, n in enumerate(noticias, start=1):
        lineas.append(f"{i}) {n['tema']}")
        lineas.append(n["titulo"])
        lineas.append(n["resumen"])
        lineas.append(n["enlace"])
        lineas.append("")
    return "\n".join(lineas).strip()


def enviar(texto):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": texto,
            "disable_web_page_preview": True,
        },
        timeout=30,
    ).raise_for_status()


if __name__ == "__main__":
    noticias = recoger()
    if not noticias:
        enviar("📰 Noticias\n\nHoy no hubo piezas fuertes de FED, oro o Bitcoin.")
    else:
        enviar(armar_mensaje(noticias))
