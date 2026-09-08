# -*- coding: utf-8 -*-
import os, re, sys, json, random, hashlib, datetime, requests, time, html as htmlmod
from xml.etree.ElementTree import parse
urllib3_disable = None
try:
    import urllib3; urllib3.disable_warnings()
except Exception:
    pass

GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
OR_KEY   = os.environ.get("OPENROUTER_KEY", "").strip()

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
SITE_URL = "https://pavrus-ai.github.io/pavrus-vk-agent"
HISTORY = "history.json"
TOPICS_FILE = "topics.json"
MAX_RSS_ITEMS = 15
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
BRANDS = ["pavrus", "chartu", "restmoment", "htdz"]
BL = ["корзин", "цен", "купить", "заказ", "доставк", "гаранти", "cookie", "политик", "в налич", "оформить", "арт.", "артикул"]

# Запасной источник: разделы каталога (даны владельцем сайта)
CATEGORY_SEEDS = [
    "https://pavrus.ru/catalog/pavrus-sistema-golosovaniya/",
    "https://pavrus.ru/catalog/pavrus-potolochnye-gromkogovoriteli/",
    "https://pavrus.ru/catalog/pavrus-nastennye-gromkogovoriteli/",
    "https://pavrus.ru/catalog/pavrus-mixer-amp/",
    "https://pavrus.ru/catalog/pavrus-konferents-sistema/",
    "https://pavrus.ru/catalog/pavrus-wireless-conferences/",
    "https://pavrus.ru/catalog/pavrus-videooborudovanie-dlya-konferents-zala/",
    "https://pavrus.ru/catalog/pavrus-sinkhronnyy-perevod/",
    "https://pavrus.ru/catalog/pavrus-acoustic-systems-line-array/",
    "https://pavrus.ru/catalog/zvukovye-protsessory/",
    "https://pavrus.ru/catalog/pavrus-mikshernye-pulty/",
    "https://pavrus.ru/catalog/pavrus-radiosistema/",
    "https://pavrus.ru/catalog/pavrus-usiliteli-moshchnosti/",
    "https://pavrus.ru/catalog/gotovye-videosteny/",
    "https://pavrus.ru/catalog/pavrus/",
    "https://pavrus.ru/catalog/pavrus-videowall-controller/",
    "https://pavrus.ru/catalog/svetodiodnyy-ekran-led-videostena/",
    "https://pavrus.ru/catalog/pavrus-proektor/",
    "https://pavrus.ru/catalog/ekran-Classic-Solution/",
    "https://pavrus.ru/catalog/pavrus-terminal-vks/",
    "https://pavrus.ru/catalog/besprovodnaya-sistema-kontenta/",
    "https://pavrus.ru/catalog/pavrus-kommutator-hdmi/",
    "https://pavrus.ru/catalog/matrichnyy-kommutator-pavrus/",
    "https://pavrus.ru/catalog/pavrus-udlinitel-po-ip-i-vitoy-pare/",
    "https://pavrus.ru/catalog/usilitel-raspredelitel-kramer/",
]

def log(msg):
    print(msg, flush=True)

log("Версия ℹ️ pavrus-dzen-agent v5 (товарные URL из вложенных sitemap + разделов, мягкий парсер, лог отбраковки)")

# ============================================================
# ИИ
# ============================================================

def _extract(r):
    try: return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError): return None

def ai_groq(prompt):
    if not GROQ_KEY: return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": "llama-3.3-70b-versatile", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
            timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_openrouter(prompt, model):
    if not OR_KEY: return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}", "HTTP-Referer": "https://github.com"},
            json={"model": model, "temperature": 0.8, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
            timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_call(prompt, minlen=2500):
    models = [
        ("groq", "llama-3.3-70b-versatile"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("openrouter", "google/gemma-3-27b-it:free"),
        ("openrouter", "deepseek/deepseek-chat-v3-0324:free"),
        ("openrouter", "auto")
    ]
    for provider, model in models:
        try:
            log(f"🔄 Попытка: {provider} ({model})...")
            res = ai_groq(prompt) if provider == "groq" else ai_openrouter(prompt, model)
            if res and len(res) >= minlen:
                log(f"✅ Успех: {provider} ({model}), {len(res)} симв.")
                return res
            elif res:
                log(f"⚠️ {provider}: короткий текст ({len(res)} симв., нужно {minlen})")
        except Exception as e:
            log(f"⚠️ {provider} ошибка: {e}")
    return None

# ============================================================
# ХЕЛПЕРЫ ПАРСИНГА
# ============================================================

def clean(s):
    for _ in range(3):
        s = htmlmod.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def abs_url(u):
    u = (u or "").strip()
    if not u or u.startswith("data:"): return ""
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"): return SITE + u
    if u.startswith("http"): return u
    return ""

def is_product_url(u):
    """Товар = /catalog/<раздел>/<товар>/ ; раздел = /catalog/<что-то>/"""
    path = u.split("?")[0].strip("/").split("/")
    return len(path) >= 3 and path[0] == "catalog"

def get_meta(r, name):
    for pat in (
        r'<meta[^>]+name=["\']' + name + r'["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']' + name + r'["\']',
    ):
        m = re.search(pat, r, re.S | re.I)
        if m:
            v = clean(m.group(1))
            if v: return v
    return ""

def get_og_image(r):
    for pat in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']',
    ):
        m = re.search(pat, r, re.S | re.I)
        if m:
            u = abs_url(m.group(1))
            if u: return u
    return ""

# ============================================================
# ЭТАП 1: СБОР ТОВАРНЫХ URL
# ============================================================

def collect_urls():
    products, sections = [], []
    try:
        log("Этап 1: загрузка главной карты сайта...")
        xml = requests.get(SITEMAP, timeout=30, headers=UA).text
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
        smps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
        log(f"ℹ️ Вложенных карт: {len(smps)}")
        for sm in smps:
            try:
                x = requests.get(sm, timeout=30, headers=UA).text
            except Exception:
                continue
            for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x):
                if "/catalog/" not in u:
                    continue
                (products if is_product_url(u) else sections).append(u)
    except Exception as e:
        log(f"⚠️ sitemap недоступен: {e}")

    products = sorted(set(products))
    sections = sorted(set(sections))
    log(f"ℹ️ Из sitemap: товаров={len(products)}, разделов={len(sections)}")

    # Если товаров мало — обходим разделы-сида и собираем карточки сами
    if len(products) < 10:
        log("Этап 1b: обход разделов каталога для сбора товарных ссылок...")
        seeds = list(set(sections + CATEGORY_SEEDS))[:40]
        for s in seeds:
            try:
                h = requests.get(s, timeout=20, headers=UA).text
            except Exception:
                continue
            for href in re.findall(r'href=["\'](/catalog/[^"\']+/[^"\']+/?)["\']', h):
                u = abs_url(href)
                if u and is_product_url(u) and u not in products:
                    products.append(u)
        products = sorted(set(products))
        log(f"ℹ️ После обхода разделов: товаров={len(products)}")

    # Приоритет — URL с брендом в адресе
    def brand_rank(u):
        ul = u.lower()
        return 0 if any(b in ul for b in BRANDS) else 1
    products.sort(key=brand_rank)
    return products

# ============================================================
# ЭТАП 2: ВЫБОР И ПАРСИНГ СТРАНИЦЫ
# ============================================================

def parse_page(r):
    title = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", r, re.S | re.I)
    if m: title = clean(m.group(1))
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", r, re.S | re.I)
        title = clean(m.group(1)) if m else ""

    desc = get_meta(r, "description") or get_meta(r, "og:description")

    tail = re.sub(r"<script[^>]*>.*?</script>", " ", r, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)

    # МЯГКИЙ парсер: абзацы И div'ы с описанием (descr/text/content/detail)
    chunks = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
    chunks += re.findall(r'<div[^>]+class=["\'][^"\']*(?:descr|text|content|detail)[^"\']*["\'][^>]*>(.*?)</div>', tail, re.S | re.I)
    raw = " ".join(clean(c) for c in chunks)
    keep = [s.strip() for s in raw.split(". ")
            if len(s.strip()) > 40 and "{" not in s
            and not any(b in s.lower() for b in BL)]
    body = " ".join(keep)[:2000]

    imgs = []
    og = get_og_image(r)
    if og: imgs.append(og)
    for tag in re.findall(r"<img[^>]+>", tail)[:12]:
        u = ""
        for attr in ("data-src", "data-lazy-src", "data-original", "src"):
            am = re.search(attr + r'\s*=\s*["\']([^"\']+)["\']', tag, re.I)
            if am and am.group(1).strip():
                u = am.group(1)
                break
        u = abs_url(u.split(",")[0].strip().split(" ")[0])
        if u and u not in imgs:
            imgs.append(u)
    return title, desc, body, imgs

def pick_page(urls, hist):
    for attempt in range(20):
        available = [u for u in urls if u not in hist]
        if not available:
            log("ℹ️ История покрывает все страницы — начинаю круг заново")
            available = urls
        page = random.choice(available[:200])
        try:
            r = requests.get(page, timeout=30, headers=UA).text
        except Exception as e:
            log(f"⚠️ Попытка {attempt+1}: страница не открылась ({page}) — {e}")
            continue
        low = r.lower()
        if not any(b in low for b in BRANDS):
            log(f"⚠️ Попытка {attempt+1}: нет бренда на странице — {page}")
            continue
        title, desc, body, imgs = parse_page(r)
        if not title or "не найдена" in title.lower() or "404" in title:
            log(f"⚠️ Попытка {attempt+1}: пустой/404 заголовок — {page}")
            continue
        if len(body) < 150 and len(desc) < 80:
            log(f"⚠️ Попытка {attempt+1}: мало текста (body={len(body)}, desc={len(desc)}) — {page}")
            continue
        log(f"✅ Попытка {attempt+1}: страница подошла — {page}")
        return page, title, desc, body, (imgs[0] if imgs else "")
    return None, "", "", "", ""

# ============================================================
# ТЕКСТ, КАРТИНКА, HTML, RSS
# ============================================================

def generate_image(title, desc):
    scene = (f"Professional AV equipment in modern conference hall: {title}. "
             f"Clean bright interior, daylight, sharp focus, photorealistic, no text, no people close-up")
    seed = int(time.time()) % 1000000
    url = ("https://image.pollinations.ai/prompt/" + requests.utils.quote(scene) +
           f"?nologo=true&seed={seed}&model=flux&width=1280&height=720")
    try:
        r = requests.get(url, timeout=240)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log(f"⚠️ Ошибка генерации картинки: {e}")
        return None

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def load_existing_rss():
    items = []
    if os.path.exists("dzen-rss.xml"):
        try:
            tree = parse("dzen-rss.xml")
            channel = tree.getroot().find("channel")
            if channel is not None:
                for item in channel.findall("item"):
                    items.append({
                        "title": item.findtext("title", ""),
                        "link": item.findtext("link", ""),
                        "guid": item.findtext("guid", ""),
                        "pub_date": item.findtext("pubDate", ""),
                        "description": item.findtext("description", ""),
                        "content": item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", ""),
                        "img_url": item.find("enclosure").get("url", "") if item.find("enclosure") is not None else ""
                    })
        except Exception as e:
            log(f"⚠️ Ошибка чтения старого RSS: {e}")
    return items

def generate_rss(new_item, existing_items):
    items_xml = ""
    for it in ([new_item] + existing_items)[:MAX_RSS_ITEMS]:
        enc = ""
        if it.get("img_url"):
            enc = f'\n    <enclosure url="{it["img_url"]}" type="image/jpeg" length="0"/>'
        items_xml += f"""  <item>
    <title>{esc(it['title'])}</title>
    <link>{it['link']}</link>
    <guid isPermaLink="true">{it['guid']}</guid>
    <pubDate>{it['pub_date']}</pubDate>
    <description>{esc(it['description'][:300])}</description>{enc}
    <content:encoded><![CDATA[{it['content']}]]></content:encoded>
  </item>
"""
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>Pavrus — Профессиональное AV-оборудование</title>
<link>{SITE_URL}</link>
<description>Обзоры профессионального аудио- и видеооборудования: Pavrus, Chartu, Restmoment, HTDZ.</description>
<language>ru-ru</language>
{items_xml}</channel>
</rss>
"""
    with open("dzen-rss.xml", "w", encoding="utf-8") as f:
        f.write(rss)
    log("✅ RSS-лента сохранена: dzen-rss.xml")

# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================

def main():
    urls = collect_urls()

    try:
        hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
    except Exception:
        hist = set()

    use_fallback = False
    page, title, desc, body, site_img = pick_page(urls, hist) if urls else (None, "", "", "", "")
    if not page:
        log("⚠️ Сайт не дал подходящую товарную страницу — беру тему из topics.json")
        use_fallback = True

    if use_fallback:
        try:
            topics = json.load(open(TOPICS_FILE, encoding="utf-8"))["topics"]
            avail = [t for t in topics if t.get("url") not in hist] or topics
            topic = random.choice(avail)
            page, title, desc, body = topic["url"], topic["title"], topic["about"], topic["about"]
            site_img = ""
            log(f"Этап 2 ✅ (fallback) Тема: «{title}»")
        except Exception as e:
            log(f"❌ Ошибка чтения topics.json: {e}")
            sys.exit(1)
    else:
        log(f"Этап 2 ✅ {page}")

    log(f"Этап 3 ✅ «{title}», основа: {len(body)} симв.")

    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)

    prompt = (
        f"Напиши развёрнутую статью для платформы Дзен о продукте компании Pavrus.\n\n"
        f"НАЗВАНИЕ ПРОДУКТА: {title}\n"
        f"ОПИСАНИЕ: {desc}\n"
        f"ХАРАКТЕРИСТИКИ И ДЕТАЛИ: {body[:1500]}\n"
        f"ССЫЛКА НА ПРОДУКТ: {page}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Длина СТРОГО 2500-4000 символов.\n"
        f"3. Первая строка — заголовок ЗАГЛАВНЫМИ буквами, без ** и ##.\n"
        f"4. Пиши как эксперт по профессиональному AV-оборудованию: живо, уникально, без пафоса.\n"
        f"5. Структура: заголовок, введение (2-3 абзаца), основная часть (4-6 абзацев), заключение.\n"
        f"6. Подчеркни профессиональное применение (конференц-залы, мероприятия).\n"
        f"7. В конце добавь: «Подробнее о продукте: {page}»"
    )
    article = ai_call(prompt, 2500) or ai_call(prompt, 1500)
    if not article:
        log("❌ Не удалось сгенерировать статью")
        sys.exit(1)
    log(f"Этап 4 ✅ Статья создана: {len(article)} символов")

    lines = article.split("\n")
    headline = lines[0].strip().upper() if lines else title.upper()
    content = "\n".join(lines[1:]).strip() if len(lines) > 1 else article

    img_bytes = generate_image(title, desc)
    if not img_bytes and site_img:
        try:
            img_bytes = requests.get(site_img, timeout=60, headers=UA).content
        except Exception:
            img_bytes = None
    if not img_bytes:
        log("❌ Нет картинки — выход")
        sys.exit(1)

    day = datetime.date.today().toordinal()
    slug = hashlib.md5(f"{title}-{day}".encode()).hexdigest()[:12]
    filename = f"a/dzen_{slug}.html"
    img_filename = f"img/dzen_{slug}.jpg"
    os.makedirs("a", exist_ok=True)
    os.makedirs("img", exist_ok=True)

    content_html = esc(content).replace("\n", "<br>\n")
    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{headline}</title>
<meta name="description" content="{esc(content[:200])}">
<meta property="og:title" content="{headline}">
<meta property="og:image" content="{SITE_URL}/{img_filename}">
<meta property="og:type" content="article">
</head>
<body style="font-family:Georgia,serif;background:#141414;color:#eee;margin:0;padding:20px">
<article style="max-width:800px;margin:0 auto">
<h1>{headline}</h1>
<img src="{SITE_URL}/{img_filename}" alt="{headline}" style="width:100%;border-radius:10px">
<div style="line-height:1.6">{content_html}</div>
<p style="margin-top:30px"><a href="{page}" style="color:#7ab8ff">📖 Подробнее о продукте</a></p>
</article>
</body>
</html>"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    with open(img_filename, "wb") as f:
        f.write(img_bytes)
    log(f"Этап 6 ✅ Сохранено: {filename}, {img_filename}")

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    new_item = {
        "title": headline,
        "link": f"{SITE_URL}/{filename}",
        "guid": f"{SITE_URL}/{filename}",
        "pub_date": now.strftime("%a, %d %b %Y %H:%M:%S +0300"),
        "description": content[:300],
        "content": content,
        "img_url": f"{SITE_URL}/{img_filename}"
    }
    generate_rss(new_item, load_existing_rss())

    log("=" * 50)
    log("✅ FINISH: статья о товаре → сайт + RSS!")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
