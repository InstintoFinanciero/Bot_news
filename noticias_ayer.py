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
    "https://news.google.com/rss/search?q=(Fed+OR+FOMC+OR+Powell+OR+%22interest+rates%22+OR+inflation)+when:1d&hl=es&gl=US&ceid=US:es",
    "https://news.google.com/rss/search?q=(gold+OR+oro+OR+XAU)+when:1d&hl=es&gl=US&ceid=US:es",
    "https://news.google.com/rss/search?q=(bitcoin+OR+BTC)+when:1d&hl=es&gl=US&ceid=US:es",
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


def normalizar(texto):
    t = texto.lower()
    t = re.sub(r"[^a-záéíóúñ0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parece_ingles(texto):
    t = f" {texto.lower()} "
    marcas = (" the ", " and ", " of ", " to ", " as ", " for ", " with ", " from ", " on ")
    return sum(1 for m in marcas if m in t) >= 2


def traducir(texto):
    texto = texto_limpio(texto)
    if not texto:
        return ""
    if not parece_ingles(texto):
        return texto
    apis = [
        (
            "https://api.mymemory.translated.net/get",
            {"q": texto[:400], "langpair": "en|es"},
            lambda d: (d.get("responseData") or {}).get("translatedText"),
        ),
        (
            "https://translate.googleapis.com/translate_a/single",
            {"client": "gtx", "sl": "en", "tl": "es", "dt": "t", "q": texto[:400]},
            lambda d: "".join(part[0] for part in d[0] if part and part[0]),
        ),
    ]
    for url, params, extraer in apis:
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            t = extraer(r.json()) or ""
            t = unescape(str(t)).strip()
            if t and "INVALID" not in t.upper() and "MYMEMORY" not in t.upper():
                return t
        except Exception:
            continue
    return texto


def resumen_es(titulo, resumen):
    tit = texto_limpio(titulo)
    base = texto_limpio(resumen)

    if base.lower().startswith(tit.lower()[:35]):
        base = base[len(tit):].strip(" -:.")

    if len(base) < 25:
        return "Más detalle en el enlace."

    base = traducir(base)
    base = re.sub(r"\s+", " ", base).strip()

    if normalizar(base)[:40] == normalizar(tit)[:40]:
        return "Más detalle en el enlace."

    if len(base) > 110:
        base = base[:107].rsplit(" ", 1)[0] + "…"
    return base


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


def es_parecida(a, b):
    pa = set(normalizar(a).split())
    pb = set(normalizar(b).split())
    if not pa or not pb:
        return False
    comunes = pa & pb
    return len(comunes) / min(len(pa), len(pb)) >= 0.6


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
    if "news.google.com" not in (url or ""):
        return url
    match = re.search(r"/articles/([A-Za-z0-9_\-]+)", url)
    if match:
        raw = match.group(1)
        raw += "=" * (-len(raw) % 4)
        try:
            decoded = base64.urlsafe_b64decode(raw).decode("latin-1", errors="ignore")
            encontrado = re.search(r"https?://[^ \x00-\x1f]+", decoded)
            if encontrado:
                cand = encontrado.group(0).split("\x00")[0]
                if "news.google.com" not in cand:
                    return cand
        except Exception:
            pass
    try:
        r = requests.get(
            url,
            timeout=15,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.url and "news.google.com" not in r.url:
            return r.url
    except Exception:
        pass
    return url


def acortar(url):
    url = enlace_real(url)
    intentos = [
        ("https://is.gd/create.php", {"format": "simple", "url": url}),
        ("https://tinyurl.com/api-create.php", {"url": url}),
        ("https://clck.ru/--", {"url": url}),
    ]
    for api, params in intentos:
        try:
            r = requests.get(api, params=params, timeout=15)
            corto = r.text.strip()
            if r.ok and corto.startswith("http") and len(corto) < 40 and "news.google.com" not in corto:
                return corto
        except Exception:
            continue
    return url


def recoger():
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS)
    vistas = set()
    por_tema = {"🏦 Fed / macro": [], "🥇 Oro": [], "🪙 Bitcoin": []}

    for url in FEEDS:
        feed = feedparser.parse(url)
        for entrada in feed.entries:
            titulo = titulo_limpio(entrada.get("title") or "Sin título")
            enlace = (entrada.get("link") or "").strip()
            resumen = texto_limpio(entrada.get("summary") or entrada.get("description") or "")
            tema = clasificar(titulo, resumen)
            blob = f"{titulo} {resumen}".lower()

            if not enlace or not tema or es_basura(titulo):
                continue
            if fecha_ok(entrada) < limite:
                continue
            if not any(p in blob for p in TEMA_OK):
                continue

            clave = normalizar(titulo)
            if clave in vistas:
                continue
            vistas.add(clave)

            item = {
                "titulo": titulo,
                "resumen": resumen_es(titulo, resumen),
                "enlace": enlace,
                "tema": tema,
                "pts": puntaje(blob),
            }
            if any(es_parecida(item["titulo"], x["titulo"]) for x in por_tema[tema]):
                continue
            por_tema[tema].append(item)

    for tema in por_tema:
        por_tema[tema].sort(key=lambda n: n["pts"], reverse=True)

    elegidas = []
    for tema in ("🏦 Fed / macro", "🥇 Oro", "🪙 Bitcoin"):
        if por_tema[tema]:
            elegidas.append(por_tema[tema].pop(0))

    resto = []
    for items in por_tema.values():
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
        if any(es_parecida(n["titulo"], x["titulo"]) for x in elegidas):
            continue
        elegidas.append(n)
        conteo[n["tema"]] = conteo.get(n["tema"], 0) + 1

    for n in elegidas:
        n["enlace"] = acortar(n["enlace"])
    return elegidas[:MAX_NOTICIAS]


def armar_mensaje(noticias):
    dias = {
        "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
        "Thursday": "jueves", "Friday": "viernes",
        "Saturday": "sábado", "Sunday": "domingo",
    }
    hoy = datetime.now()
    dia = dias.get(hoy.strftime("%A"), hoy.strftime("%A"))
    lineas = [f"📰 Noticias · {dia} {hoy:%d/%m}", ""]

    for i, n in enumerate(noticias, start=1):
        lineas.append(f"{i}) {n['tema']}")
        lineas.append(n["titulo"])
        if normalizar(n["resumen"]) != normalizar(n["titulo"]):
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
