# -*- coding: utf-8 -*-
import os, re, json, random, sys, time, datetime, requests, html, base64, uuid
from urllib.parse import urljoin

GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
GROQ_KEY2 = os.environ.get("GROQ_KEY2", "").strip()
OR_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
OR_KEY2 = os.environ.get("OPENROUTER_KEY2", "").strip()
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "").strip()
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "").strip()
GH_AI_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "articles_history.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}

# ⚠️ СТРОГО только PAVRUS
BRAND_SLUG = "pavrus"

# Список городов и мусора для очистки
JUNK_PATTERNS = [
    r"Санкт-Петербург|Москва|Новосибирск|Краснодар|Красноярск",
    r"Войти|Выйти|Регистрация|Личный кабинет",
    r"Каталог|Компания|Информация|Контакты|Доставка|Оплата",
    r"Заказать звонок|Обратная связь|Назад к списку",
    r"Выбрать автоматически|Ваш город",
    r"8 \(800|info@|показать еще",
    r"корзин|кабинет|избранн|сравнени",
]

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

log("Версия ℹ️ pavrus-articles-agent v4 (чистый парсинг + умная генерация + только бренд PAVRUS)")

# ============================================================
# ИИ-ГЕНЕРАЦИЯ (8 ступеней)
# ============================================================

def _extract(r):
    try: return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError): return None

RU_SUFFIX = "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."

def ai_github(prompt):
    if not GH_AI_TOKEN: return None
    endpoints = ["https://models.github.ai/inference/chat/completions",
                 "https://models.inference.ai.azure.com/chat/completions"]
    models = ["openai/gpt-4o-mini", "gpt-4o-mini"]
    for ep in endpoints:
        for mdl in models:
            try:
                r = requests.post(ep,
                    headers={"Authorization": f"Bearer {GH_AI_TOKEN}"},
                    json={"model": mdl, "temperature": 0.7,
                          "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=90).json()
                if "error" in r: continue
                res = _extract(r)
                if res: return res
            except Exception:
                continue
    return None

def ai_cerebras(prompt):
    if not CEREBRAS_KEY: return None
    try:
        r = requests.post("https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_KEY}"},
            json={"model": "llama-3.3-70b", "temperature": 0.7,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=90).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_mistral(prompt):
    if not MISTRAL_KEY: return None
    try:
        r = requests.post("https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_KEY}"},
            json={"model": "mistral-small-latest", "temperature": 0.7,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=90).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_groq(prompt, key):
    if not key: return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "llama-3.3-70b-versatile", "temperature": 0.7,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=90).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_openrouter(prompt, model, key):
    if not key: return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com"},
            json={"model": model, "temperature": 0.7, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=90).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_call(prompt, minlen=800):
    """Пытается все модели, возвращает первый успешный результат."""
    # 1) GitHub Models
    if GH_AI_TOKEN:
        log("🔄 Попытка: github-models (gpt-4o-mini)...")
        res = ai_github(prompt)
        if res and len(res) >= minlen:
            log(f"✅ Успех: github-models, {len(res)} симв.")
            return res
    
    # 2) Cerebras
    if CEREBRAS_KEY:
        log("🔄 Попытка: cerebras (llama-3.3-70b)...")
        res = ai_cerebras(prompt)
        if res and len(res) >= minlen:
            log(f"✅ Успех: cerebras, {len(res)} симв.")
            return res
    
    # 3) Mistral
    if MISTRAL_KEY:
        log("🔄 Попытка: mistral (mistral-small)...")
        res = ai_mistral(prompt)
        if res and len(res) >= minlen:
            log(f"✅ Успех: mistral, {len(res)} симв.")
            return res
    
    # 4) Groq ×2
    for i, key in enumerate((GROQ_KEY, GROQ_KEY2)):
        if not key: continue
        log(f"🔄 Попытка: groq (ключ {i+1})...")
        res = ai_groq(prompt, key)
        if res and len(res) >= minlen:
            log(f"✅ Успех: groq (ключ {i+1}), {len(res)} симв.")
            return res
    
    # 5) OpenRouter ×4 ×2
    or_models = ["meta-llama/llama-3.3-70b-instruct:free",
                 "google/gemma-3-27b-it:free",
                 "deepseek/deepseek-chat-v3-0324:free",
                 "auto"]
    for i, key in enumerate((OR_KEY, OR_KEY2)):
        if not key: continue
        for model in or_models:
            log(f"🔄 Попытка: openrouter ({model}, ключ {i+1})...")
            res = ai_openrouter(prompt, model, key)
            if res and len(res) >= minlen:
                log(f"✅ Успех: openrouter ({model}, ключ {i+1}), {len(res)} симв.")
                return res
    
    return None

# ============================================================
# ПАРСИНГ САЙТА (чистый)
# ============================================================

def clean(s):
    """Очищает текст от HTML и мусора."""
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    # Удаляем мусор
    for pattern in JUNK_PATTERNS:
        s = re.sub(pattern, "", s, flags=re.IGNORECASE)
    # Чистим пробелы
    s = re.sub(r"\s+", " ", s).strip()
    return s

def abs_url(u):
    u = (u or "").strip()
    if not u or u.startswith("data:"): return ""
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"): return SITE + u
    if u.startswith("http"): return u
    return ""

def is_pavrus_brand(u):
    """СТРОГО: только товары бренда PAVRUS."""
    path = u.split("//", 1)[-1].split("/", 1)[-1].lower()
    return BRAND_SLUG in path

def fetch_sitemap():
    urls = []
    try:
        xml = requests.get(SITEMAP, timeout=30, headers=UA).text
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
        smps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
        for sm in smps:
            try:
                x = requests.get(sm, timeout=30, headers=UA).text
                urls += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x) if "/catalog/" in u]
            except Exception: continue
    except Exception as e:
        log(f"️ Sitemap недоступен: {e}")
        return []
    
    urls = sorted(set(urls))
    
    # ФИЛЬТР: оставляем ТОЛЬКО товары PAVRUS
    pavrus_urls = [u for u in urls if is_pavrus_brand(u)]
    log(f"ℹ️ Этап 1: всего ссылок /catalog/: {len(urls)}")
    log(f"🎯 После фильтра по бренду PAVRUS: {len(pavrus_urls)} ссылок")
    
    if len(pavrus_urls) < 10:
        log("⚠️ Мало ссылок PAVRUS — обход разделов каталога")
        for s in CATEGORY_SEEDS:
            try:
                h = requests.get(s, timeout=20, headers=UA).text
                for href in re.findall(r'href=["\'](/catalog/[^"\']+)["\']', h):
                    u = abs_url(href)
                    if u and u not in pavrus_urls and is_pavrus_brand(u):
                        pavrus_urls.append(u)
            except Exception: continue
        pavrus_urls = sorted(set(pavrus_urls))
        log(f" После обхода разделов: {len(pavrus_urls)} ссылок PAVRUS")
    
    if not pavrus_urls:
        raise RuntimeError("Нет ссылок на товары PAVRUS")
    return pavrus_urls

def parse_page(html_text):
    """Извлекает только полезный контент со страницы товара."""
    # H1
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    if m: h1 = clean(m.group(1))
    
    # Мета-описание
    desc = ""
    dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_text, re.S | re.I)
    if dm: desc = clean(dm.group(1))
    
    # Основной контент — ищем только в описании товара
    tail = html_text
    
    # Удаляем скрипты и стили
    tail = re.sub(r"<script[^>]*>.*?</script>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    
    # Удаляем навигацию и меню
    tail = re.sub(r"<nav[^>]*>.*?</nav>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<header[^>]*>.*?</header>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<footer[^>]*>.*?</footer>", " ", tail, flags=re.S | re.I)
    
    # Ищем только описание товара (обычно в div с классом description или detail)
    desc_block = ""
    for cls in ["description", "descr", "detail", "product-description", "tab-content"]:
        m = re.search(rf'<div[^>]+class=["\'][^"\']*{cls}[^"\']*["\'][^>]*>(.*?)</div>', tail, re.S | re.I)
        if m:
            desc_block = m.group(1)
            break
    
    if not desc_block:
        # Если не нашли блок описания, берём все абзацы
        chunks = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
        desc_block = " ".join(chunks)
    
    # Чистим текст
    raw = clean(desc_block)
    
    # Разбиваем на предложения и оставляем только осмысленные
    sentences = raw.split(". ")
    keep = []
    for s in sentences:
        s = s.strip()
        if len(s) < 20: continue
        if "{" in s or "}" in s: continue
        # Проверяем, что это не мусор
        if any(junk in s.lower() for junk in ["корзин", "кабинет", "войти", "каталог", "контакты"]):
            continue
        keep.append(s)
    
    body = ". ".join(keep)[:1500]
    
    return h1, desc, body

def pick_page(urls, hist):
    """Выбирает случайную страницу PAVRUS, которой ещё не было."""
    avail = [u for u in urls if u not in hist] or urls
    page = random.choice(avail)
    
    try:
        rs = requests.get(page, timeout=30, headers=UA)
        if rs.status_code != 200 or len(rs.text) < 3000:
            return None, "", "", ""
        r = rs.text
        
        h1, desc, body = parse_page(r)
        if not h1 or (len(body) + len(desc)) < 50:
            log(f"⚠️ Страница {page}: мало текста (H1={h1[:50]}, body={len(body)})")
            return None, "", "", ""
        
        log(f"✅ Этап 2: товар PAVRUS «{h1[:70]}» — {page}")
        log(f"   Описание: {desc[:100]}...")
        log(f"   Текст: {body[:100]}...")
        return page, h1, desc, body
    except Exception as e:
        log(f"⚠️ Ошибка загрузки {page}: {e}")
        return None, "", "", ""

# ============================================================
# ГЕНЕРАЦИЯ СТАТЬИ И НОВОСТИ
# ============================================================

def generate_article(title, desc, body, url):
    """Генерирует статью на основе чистых данных."""
    # Простой промпт
    prompt = (
        f"Напиши статью о товаре PAVRUS.\n\n"
        f"Название: {title}\n"
        f"Краткое описание: {desc}\n"
        f"Характеристики: {body[:500]}\n\n"
        f"Требования:\n"
        f"1. Длина 800-1500 символов.\n"
        f"2. HTML-разметка: <h2> для разделов, <p> для текста.\n"
        f"3. Структура:\n"
        f"   <h2>Что это такое</h2>\n"
        f"   <p>введение</p>\n"
        f"   <h2>Применение</h2>\n"
        f"   <p>где используется</p>\n"
        f"   <h2>Особенности</h2>\n"
        f"   <p>преимущества</p>\n"
        f"4. В конце: «По вопросам обращайтесь к специалистам PAVRUS».\n"
        f"5. Пиши как эксперт по AV-оборудованию."
    )
    
    article = ai_call(prompt, minlen=800)
    if article:
        return article
    
    # Если ИИ не сработал, создаём минимальную статью из чистых данных
    log("⚠️ ИИ недоступны — создаю минимальную статью из данных")
    return f"""<h2>{title}</h2>
<p>{desc if desc else 'Профессиональное AV-оборудование PAVRUS.'}</p>
<h2>Применение</h2>
<p>Используется в конференц-залах, на мероприятиях и презентациях.</p>
<h2>Особенности</h2>
<p>{body[:300] if body else 'Высокое качество и надёжность.'}</p>
<p>По вопросам обращайтесь к специалистам PAVRUS.</p>"""

def generate_news_from_article(article, title, url):
    """Создаёт новость на основе статьи."""
    # Извлекаем чистый текст
    plain_text = re.sub(r"<[^>]+>", " ", article).strip()
    plain_text = re.sub(r"\s+", " ", plain_text)
    
    prompt = (
        f"Создай краткую новость (500-800 символов) на основе статьи.\n\n"
        f"Статья: {plain_text[:1000]}\n"
        f"Товар: {title}\n\n"
        f"Требования:\n"
        f"1. HTML-разметка: <h2> заголовок, <p> текст.\n"
        f"2. 2-3 абзаца.\n"
        f"3. В конце: «Подробнее у специалистов PAVRUS»."
    )
    
    news = ai_call(prompt, minlen=400)
    if news:
        return news
    
    # Фолбэк: берём первые 600 символов статьи
    log("⚠️ Не удалось сгенерировать новость — сжимаю статью")
    short = plain_text[:600].rsplit(".", 1)[0] + "."
    return f"<h2>{title}</h2><p>{short}</p><p>Подробнее у специалистов PAVRUS.</p>"

# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================

def main():
    try:
        hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
    except Exception:
        hist = set()
    
    urls = fetch_sitemap()
    if not urls:
        log("❌ Не удалось получить ссылки PAVRUS с сайта")
        sys.exit(1)
    
    page, title, desc, body = pick_page(urls, hist)
    if not page:
        log("❌ Не найдена подходящая страница PAVRUS")
        sys.exit(1)
    
    log("📝 Этап 3: генерация статьи...")
    article = generate_article(title, desc, body, page)
    if not article:
        log("❌ Не удалось сгенерировать статью")
        sys.exit(1)
    
    log("📰 Этап 4: генерация новости...")
    news = generate_news_from_article(article, title, page)
    if not news:
        log("❌ Не удалось сгенерировать новость")
        sys.exit(1)
    
    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)
    
    log("=" * 60)
    log(f"🎯 ТОВАР PAVRUS: {title}")
    log(f"🔗 ССЫЛКА: {page}")
    log("=" * 60)
    log("✅ СТАТЬЯ:")
    log(article[:500] + ("..." if len(article) > 500 else ""))
    log(f"   Длина: {len(article)} симв.")
    log("=" * 60)
    log("✅ НОВОСТЬ:")
    log(news[:300] + ("..." if len(news) > 300 else ""))
    log(f"   Длина: {len(news)} симв.")
    log("=" * 60)
    log("✅ FINISH: статья и новость по товару PAVRUS сгенерированы!")
    log("=" * 60)
    
    output_dir = "articles_output"
    os.makedirs(output_dir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50]
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    
    with open(f"{output_dir}/{date_str}_{slug}_article.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body><h1>{title} (PAVRUS)</h1>{article}<p><a href='{page}'>Подробнее на сайте</a></p></body></html>")
    
    with open(f"{output_dir}/{date_str}_{slug}_news.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body>{news}<p><a href='{page}'>Подробнее</a></p></body></html>")
    
    with open(f"{output_dir}/{date_str}_{slug}_texts.txt", "w", encoding="utf-8") as f:
        f.write(f"ТОВАР PAVRUS: {title}\nССЫЛКА: {page}\n\n=== СТАТЬЯ ===\n{article}\n\n=== НОВОСТЬ ===\n{news}")
    
    log(f"💾 Файлы сохранены в папке {output_dir}/")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
