# -*- coding: utf-8 -*-
import os, re, json, html, random, sys, urllib.parse, requests, io, time, datetime
from xml.etree.ElementTree import Element, SubElement, tostring, parse
from xml.dom import minidom

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "dzen_history.json"
TOPICS_FILE = "topics.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Ключи: сначала пробуем KEY2 (для Дзена), если нет — обычные
GROQ_KEY = os.getenv("GROQ_KEY2", "") or os.getenv("GROQ_KEY", "")
OR_KEY = os.getenv("OPENROUTER_KEY2", "") or os.getenv("OPENROUTER_KEY", "")

BRANDS = ["pavrus", "chartu", "restmoment", "htdz"]
BL = ["Корзина", "Кабинет", "Избранные", "Сравнение", "Каталог", "Войти",
      "Заказать звонок", "Санкт-Петербург", "Москва", "Новосибирск",
      "8 (800)", "info@", "pavrus.ru", "Показать еще", "Ваш город",
      "Бесплатная доставка", "Главная", "Обратная связь"]

SITE_URL = "https://pavrus-ai.github.io/pavrus-vk-agent"
MAX_RSS_ITEMS = 15

def log(msg): print(msg, flush=True)
log("Версия ℹ️ pavrus-dzen-agent v4 (с защитой от падения сайта pavrus.ru)")

# --- ИИ ---
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
    log("❌ Все попытки генерации ИИ не удались")
    return None

def clean(s):
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def abs_url(u):
    u = u.strip()
    if not u or u.startswith("data:"): return ""
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"): return SITE + u
    if u.startswith("http"): return u
    return ""

# --- Этап 1: Попытка взять со сайта, иначе fallback на topics.json ---
urls = []
use_fallback = False

try:
    log("Этап 1: Попытка загрузки sitemap с pavrus.ru...")
    xml = requests.get(SITEMAP, timeout=30, headers=UA).text
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
    smps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
    
    all_urls = []
    for sm in smps:
        x = requests.get(sm, timeout=30, headers=UA).text
        all_urls += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x) if "/catalog/" in u]
    
    all_urls = sorted(set(all_urls))
    
    # Фильтруем по брендам
    catalog_urls = []
    for u in all_urls[:50]: # Проверяем первые 50, чтобы не ждать вечно
        try:
            r = requests.get(u, timeout=15, headers=UA)
            if any(brand in r.text.lower() for brand in BRANDS):
                catalog_urls.append(u)
        except:
            continue
    
    urls = catalog_urls if catalog_urls else [u for u in all_urls if "/catalog/" in u]
    if not urls:
        raise RuntimeError("Нет страниц в /catalog/")
    log(f"Этап 1 ✅ Найдено страниц на сайте: {len(urls)}")
    
except Exception as e:
    log(f"⚠️ Сайт pavrus.ru недоступен или sitemap изменён: {e}")
    log("🔄 Переключаюсь на резервный источник: topics.json")
    use_fallback = True

# --- Этап 2: Выбор страницы или темы ---
try:
    hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
except:
    hist = set()

title = body = page = desc = site_img = ""
img_cands = []

if use_fallback:
    try:
        topics_data = json.load(open(TOPICS_FILE, encoding="utf-8"))["topics"]
        available_topics = [t for t in topics_data if t.get("url") not in hist]
        if not available_topics:
            hist.clear()
            available_topics = topics_data
        
        topic = random.choice(available_topics)
        page = topic["url"]
        title = topic["title"]
        desc = topic["about"]
        body = topic["about"] # Для Дзена ИИ развернет это в полную статью
        site_img = "https://via.placeholder.com/1280x720/1e1e14/7ab8ff?text=PAVRUS" # Заглушка, ИИ сгенерирует свою или возьмем из интернета если есть
        log(f"Этап 2 ✅ (Fallback) Тема: «{title}»")
    except Exception as e:
        log(f"❌ Ошибка чтения topics.json: {e}")
        sys.exit(1)
else:
    # Стандартная логика парсинга сайта
    for attempt in range(15):
        available = [u for u in urls if u not in hist]
        if not available:
            hist.clear()
            available = urls
        
        page = random.choice(available)
        try:
            r = requests.get(page, timeout=30, headers=UA).text
        except:
            continue
        
        page_lower = r.lower()
        if not any(brand in page_lower for brand in BRANDS):
            continue
        
        m = re.search(r"<title[^>]*>(.*?)</title>", r, re.S | re.I)
        title = clean(m.group(1)) if m else ""
        
        dm = (re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', r, re.S | re.I)
              or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', r, re.S | re.I)
              or re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)', r, re.S | re.I))
        desc = clean(dm.group(1)) if dm else ""
        
        tail = r[m.end():] if m else r
        tail = re.sub(r"<script[^>]*>.*?</script>", " ", tail, flags=re.S | re.I)
        tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
        
        img_cands = []
        og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']*)', r, re.S | re.I)
        if og:
            u = abs_url(og.group(1))
            if u: img_cands.append(u)
        
        for mm in re.finditer(r"<img[^>]+>", tail, re.S | re.I):
            tag = mm.group(0)
            u = ""
            for attr in ["data-src", "data-lazy-src", "data-original", "src"]:
                am = re.search(attr + r'=["\']([^"\']*)', tag, re.I)
                if am and am.group(1).strip():
                    u = am.group(1).split(",")[0].strip().split(" ")[0] if attr == "srcset" else am.group(1)
                    break
            u = abs_url(u)
            if u and u not in img_cands:
                img_cands.append(u)
        
        site_img = img_cands[0] if img_cands else ""
        paras = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
        raw = " ".join(clean(p) for p in paras)
        keep = [s for s in raw.split(". ") if len(s) > 40 and "{" not in s and '"' not in s and not any(b in s for b in BL)]
        body = " ".join(keep)[:2000]
        
        if title and "не найдена" not in title.lower() and (len(body) > 200 or len(desc) > 100):
            break

    if not (title and body):
        log("❌ Не удалось найти подходящую страницу на сайте")
        sys.exit(1)
    
    log(f"Этап 2 ✅ {page}")

log(f"Этап 3 ✅ «{title}», текст для основы: {len(body)} симв.")

hist.add(page)
json.dump(list(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)

# --- Этап 4: Генерация длинной статьи для Дзена ---
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

article = ai_call(prompt, minlen=2500)
if not article:
    log("❌ Не удалось сгенерировать статью")
    sys.exit(1)

log(f"Этап 4 ✅ Статья создана: {len(article)} символов")

lines = article.split('\n')
headline = lines[0].strip().upper() if lines else title.upper()
content = '\n'.join(lines[1:]).strip() if len(lines) > 1 else article

# --- Этап 5: Скачиваем картинку (или генерируем, если сайт лежит) ---
img_bytes = b""
best_w = 0

if not use_fallback:
    for u in img_cands[:6]:
        try:
            rs = requests.get(u, timeout=15, headers=UA)
            if not rs.headers.get("content-type", "").startswith("image"): continue
            if not (1000 < len(rs.content) < 5000000): continue
            img_bytes = rs.content
            break
        except Exception:
            continue

# Если картинку со сайта взять не удалось (или это fallback), генерируем через Pollinations
if not img_bytes:
    log("🎨 Генерация картинки через Pollinations (так как сайт недоступен или картинка не скачалась)...")
    scene_prompt = urllib.parse.quote(f"Professional photo: AV equipment, {title}, photorealistic, bright vivid colors, conference room setting, high resolution, no text")
    url = f"https://image.pollinations.ai/prompt/{scene_prompt}?width=1280&height=720&nologo=true&seed={random.randint(1,999999)}&model=flux"
    try:
        rs = requests.get(url, timeout=120)
        if rs.headers.get("content-type", "").startswith("image"):
            img_bytes = rs.content
    except Exception as e:
        log(f"⚠️ Ошибка генерации картинки: {e}")

if not img_bytes:
    log("❌ Не удалось получить картинку")
    sys.exit(1)

log(f"Этап 5 ✅ Картинка: {len(img_bytes)} байт")

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

with open(filename, 'w', encoding='utf-8') as f:
    f.write(html_content)
with open(img_filename, 'wb') as f:
    f.write(img_bytes)

log(f"Этап 6 ✅ Сохранено: {filename}, {img_filename}")

# --- Этап 7: RSS (без изменений, работает идеально) ---
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
            log(f"⚠️ Ошибка чтения старого RSS: {e}")
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
