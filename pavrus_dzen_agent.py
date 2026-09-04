# -*- coding: utf-8 -*-
import os, re, json, html, random, sys, urllib.parse, requests, io, time, datetime
from xml.etree.ElementTree import Element, SubElement, tostring, parse
from xml.dom import minidom

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "dzen_history.json"
UA = {"User-Agent": "Mozilla/5.0 (pavrus-dzen-agent)"}

OR_KEY = os.getenv("OPENROUTER_KEY", "")
GROQ_KEY = os.getenv("GROQ_KEY", "")

# Только эти бренды
BRANDS = ["pavrus", "chartu", "restmoment", "htdz"]

# Блокировка нежелательных слов
BL = ["Корзина", "Кабинет", "Избранные", "Сравнение", "Каталог", "Войти", 
      "Заказать звонок", "Санкт-Петербург", "Москва", "Новосибирск", 
      "8 (800)", "info@", "pavrus.ru", "Показать еще", "Ваш город",
      "Бесплатная доставка", "Главная", "Обратная связь"]

SITE_URL = "https://pavrus-ai.github.io/pavrus-vk-agent"
MAX_RSS_ITEMS = 15

def log(msg):
    print(msg, flush=True)

log("Версия ℹ️ pavrus-dzen-agent v1 (только /catalog/, бренды Pavrus/Chartu/Restmoment/HTDZ)")

# --- ИИ (те же модели, что в agent.py) ---
def _extract(r):
    try:
        return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None

def ai_groq(prompt):
    if not GROQ_KEY:
        return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": "llama-3.3-70b-versatile", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
            timeout=60).json()
        if "error" in r:
            return None
        return _extract(r)
    except Exception:
        return None

def ai_openrouter(prompt, model):
    if not OR_KEY:
        return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}", "HTTP-Referer": "https://github.com"},
            json={"model": model, "temperature": 0.8, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
            timeout=60).json()
        if "error" in r:
            return None
        return _extract(r)
    except Exception:
        return None

def ai_call(prompt, minlen=2000):
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
    
    log("❌ Все попытки генерации ИИ не удались")
    return None

# --- Утилиты ---
def clean(s):
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def abs_url(u):
    u = u.strip()
    if not u or u.startswith("data:"):
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return SITE + u
    if u.startswith("http"):
        return u
    return ""

def good_text(t):
    if not t or len(t) < 100:
        return False
    th = ["additional text:", "1. analyze"]
    return not any(m in t.lower() for m in th)

# --- Этап 1: Парсинг sitemap ---
try:
    xml = requests.get(SITEMAP, timeout=60, headers=UA).text
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
    smps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
    urls = []
    for sm in smps:
        x = requests.get(sm, timeout=60, headers=UA).text
        # Только /catalog/
        urls += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x)
                 if "/catalog/" in u]
    urls = sorted(set(urls))
    if not urls:
        raise RuntimeError("не найдено страниц в /catalog/")
    log(f"Этап 1 ✅ страниц в каталоге: {len(urls)}")
except Exception as e:
    log(f"Этап 1 ❌ {e}")
    sys.exit(1)

# --- Этап 2: Выбор страницы ---
try:
    hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
except:
    hist = set()

title = body = page = desc = site_img = ""
img_cands = []

for _ in range(10):
    # Берём случайную страницу, которую ещё не использовали
    available = [u for u in urls if u not in hist]
    if not available:
        hist.clear()  # Если все использованы, очищаем историю
        available = urls
    
    page = random.choice(available)
    r = requests.get(page, timeout=60, headers=UA).text
    
    # Проверяем бренд
    page_lower = r.lower()
    if not any(brand in page_lower for brand in BRANDS):
        log(f"⚠️ Пропуск: {page} (не найдены бренды)")
        continue
    
    # Извлекаем заголовок
    m = re.search(r"<title[^>]*>(.*?)</title>", r, re.S | re.I)
    title = clean(m.group(1)) if m else ""
    
    # Извлекаем описание
    dm = (re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', r, re.S | re.I)
          or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', r, re.S | re.I)
          or re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)', r, re.S | re.I))
    desc = clean(dm.group(1)) if dm else ""
    
    # Извлекаем основной текст
    tail = r[m.end():] if m else r
    tail = re.sub(r"<script[^>]*>.*?</script>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<nav[^>]*>.*?</nav>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<footer[^>]*>.*?</footer>", " ", tail, flags=re.S | re.I)
    
    for mk in ["Назад к списку", "Нужна консультация", "Подробная информация"]:
        i = tail.find(mk)
        if i != -1:
            tail = tail[:i]
    
    # Извлекаем картинки
    img_cands = []
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']*)', r, re.S | re.I)
    if og:
        u = abs_url(og.group(1))
        if u:
            img_cands.append(u)
    
    for mm in re.finditer(r"<img[^>]+>", tail, re.S | re.I):
        tag = mm.group(0)
        u = ""
        for attr in ["data-src", "data-lazy-src", "data-original"]:
            am = re.search(attr + r'=["\']([^"\']*)', tag, re.I)
            if am and am.group(1).strip():
                u = am.group(1)
                break
        if not u:
            am = re.search(r'srcset=["\']([^"\']*)', tag, re.I)
            if am and am.group(1).strip():
                u = am.group(1).split(",")[0].strip().split(" ")[0]
        if not u:
            am = re.search(r'src=["\']([^"\']*)', tag, re.I)
            if am:
                u = am.group(1)
        u = abs_url(u)
        if u and u not in img_cands:
            img_cands.append(u)
    
    site_img = img_cands[0] if img_cands else ""
    
    # Извлекаем параграфы
    paras = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
    raw = " ".join(clean(p) for p in paras)
    
    # Фильтруем нежелательные слова
    keep = [s for s in raw.split(". ") if len(s) > 40 and "{" not in s and '"' not in s and not any(b in s for b in BL)]
    body = " ".join(keep)[:2000]
    
    if title and "не найдена" not in title.lower() and (len(body) > 200 or len(desc) > 100) and site_img:
        break
    
    log(f"Этап 2 ⚠️ {page}: title={len(title)}, body={len(body)}, img={len(img_cands)}")

if not (title and body and site_img):
    log(" Не удалось найти подходящую страницу")
    sys.exit(1)

log(f"Этап 2 ✅ {page}")
log(f"Этап 3 ✅ «{title}», desc: {len(desc)}, text: {len(body)}, фото: {len(img_cands)} канд.")

# Добавляем в историю
hist.add(page)
json.dump(list(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)

# --- Этап 4: Генерация статьи ---
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
    f"4. Пиши как эксперт по профессиональному AV-оборудованию: живо, уникально, без пафоса и кликбейта.\n"
    f"5. Структура: заголовок, введение (2-3 абзаца), основная часть (4-6 абзацев с описанием преимуществ и применения), заключение.\n"
    f"6. Подчеркни профессиональное применение оборудования (конференц-залы, презентации, мероприятия).\n"
    f"7. В конце добавь: «Подробнее о продукте: {page}»\n\n"
    f"Статья должна быть полезной для специалистов по AV-оборудованию и интеграции."
)

article = ai_call(prompt, minlen=2500)
if not article:
    log("❌ Не удалось сгенерировать статью")
    sys.exit(1)

log(f"Этап 4 ✅ Статья создана: {len(article)} символов")

# Извлекаем заголовок (первая строка)
lines = article.split('\n')
headline = lines[0].strip().upper() if lines else title.upper()
content = '\n'.join(lines[1:]).strip() if len(lines) > 1 else article

# --- Этап 5: Скачиваем картинку со страницы ---
img_bytes = b""
best_w = 0
best_wh = (0, 0)

for u in img_cands[:6]:
    try:
        rs = requests.get(u, timeout=30, headers=UA)
        if not rs.headers.get("content-type", "").startswith("image"):
            continue
        if not (1000 < len(rs.content) < 5000000):
            continue
        
        # Проверяем размер картинки
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(rs.content))
            w, h = im.size
            if w * h > best_w:
                best_w = w * h
                best_wh = (w, h)
                img_bytes = rs.content
            if w >= 1000:
                break
        except:
            img_bytes = rs.content
            break
    except Exception:
        continue

if not img_bytes:
    log("⚠️ Не удалось скачать картинку")
    sys.exit(1)

log(f"Этап 5 ✅ Картинка: {len(img_bytes)} байт, размер: {best_wh}")

# --- Этап 6: Сохранение HTML ---
day = datetime.date.today().toordinal()
slug = hashlib.md5(f"{title}-{day}".encode()).hexdigest()[:12]
filename = f"a/dzen_{slug}.html"
img_filename = f"img/dzen_{slug}.jpg"

os.makedirs("a", exist_ok=True)
os.makedirs("img", exist_ok=True)

content_escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
content_html = content_escaped.replace('\n', '<br>\n')

html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{headline}</title>
    <meta name="description" content="{content[:200]}">
    <meta property="og:title" content="{headline}">
    <meta property="og:description" content="{content[:200]}">
    <meta property="og:image" content="{SITE_URL}/{img_filename}">
    <meta property="og:type" content="article">
</head>
<body style="font-family:Georgia,serif;background:#141414;color:#eee;margin:0;padding:20px">
    <article style="max-width:800px;margin:0 auto">
        <h1>{headline}</h1>
        <img src="{SITE_URL}/{img_filename}" alt="{headline}" style="width:100%;border-radius:10px">
        <div style="line-height:1.6">{content_html}</div>
        <p style="margin-top:30px"><a href="{page}" style="color:#7ab8ff"> Подробнее о продукте</a></p>
    </article>
</body>
</html>"""

with open(filename, 'w', encoding='utf-8') as f:
    f.write(html_content)

with open(img_filename, 'wb') as f:
    f.write(img_bytes)

log(f"Этап 6 ✅ Статья сохранена: {filename}")
log(f"Этап 6 ✅ Картинка сохранена: {img_filename}")

# --- Этап 7: RSS ---
def load_existing_rss():
    items = []
    if os.path.exists("dzen-rss.xml"):
        try:
            tree = parse("dzen-rss.xml")
            root = tree.getroot()
            channel = root.find("channel")
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
            log(f"️ Ошибка чтения старого RSS: {e}")
    return items

def generate_rss(new_item, existing_items):
    rss = Element('rss', version='2.0')
    rss.set('xmlns:content', 'http://purl.org/rss/1.0/modules/content/')
    rss.set('xmlns:atom', 'http://www.w3.org/2005/Atom')

    channel = SubElement(rss, 'channel')
    SubElement(channel, 'title').text = "Pavrus — Профессиональное AV-оборудование"
    SubElement(channel, 'link').text = SITE_URL
    SubElement(channel, 'description').text = "Обзоры профессионального аудио- и видеооборудования: Pavrus, Chartu, Restmoment, HTDZ."
    SubElement(channel, 'language').text = "ru-ru"

    all_items = ([new_item] + existing_items)[:MAX_RSS_ITEMS]

    for item in all_items:
        entry = SubElement(channel, 'item')
        SubElement(entry, 'title').text = item['title']
        SubElement(entry, 'link').text = item['link']
        g = SubElement(entry, 'guid')
        g.text = item['guid']
        g.set('isPermaLink', 'true')
        SubElement(entry, 'pubDate').text = item['pub_date']
        SubElement(entry, 'description').text = item['description']
        
        ce = SubElement(entry, '{http://purl.org/rss/1.0/modules/content/}encoded')
        ce.text = f"<![CDATA[{item['content']}]]>"
        
        if item.get('img_url'):
            enc = SubElement(entry, 'enclosure')
            enc.set('url', item['img_url'])
            enc.set('type', 'image/jpeg')
            enc.set('length', '0')

    xml_str = minidom.parseString(tostring(rss, encoding='unicode')).toprettyxml(indent="  ")
    with open('dzen-rss.xml', 'w', encoding='utf-8') as f:
        f.write(xml_str)
    log("✅ RSS-лента сохранена: dzen-rss.xml")

now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
pub_date = now.strftime("%a, %d %b %Y %H:%M:%S +0300")

new_item = {
    "title": headline,
    "link": f"{SITE_URL}/{filename}",
    "guid": f"{SITE_URL}/{filename}",
    "pub_date": pub_date,
    "description": content[:300],
    "content": content,
    "img_url": f"{SITE_URL}/{img_filename}"
}

existing = load_existing_rss()
generate_rss(new_item, existing)

log("=" * 50)
log("✅ FINISH: статья и RSS для Дзена Pavrus готовы!")
log("=" * 50)
