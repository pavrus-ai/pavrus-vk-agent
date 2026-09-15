# -*- coding: utf-8 -*-
import os, re, json, random, sys, time, datetime, requests, html
from urllib.parse import urljoin

GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
OR_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = os.environ.get("SMTP_PORT", "587").strip()
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
EMAIL_TO = os.environ.get("EMAIL_TO", "").strip()

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "articles_history.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
BRAND_SLUGS = ["pavrus"]
CATEGORY_SEEDS = [
    "https://pavrus.ru/catalog/pavrus-sistema-golosovaniya/",
    "https://pavrus.ru/catalog/pavrus-potolochnye-gromkogovoriteli/",
    "https://pavrus.ru/catalog/pavrus-konferents-sistema/",
    "https://pavrus.ru/catalog/pavrus-mikshernye-pulty/",
    "https://pavrus.ru/catalog/pavrus-usiliteli-moshchnosti/",
]

def log(msg):
    print(msg, flush=True)

log("Версия ℹ️ pavrus-articles-agent v1 (генерация статей и новостей с HTML-разметкой)")

# ============================================================
# ИИ-ГЕНЕРАЦИЯ
# ============================================================

def _extract(r):
    try: return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError): return None

def ai_groq(prompt):
    if not GROQ_KEY: return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": "llama-3.3-70b-versatile", "temperature": 0.7,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=90).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_openrouter(prompt, model):
    if not OR_KEY: return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}", "HTTP-Referer": "https://github.com"},
            json={"model": model, "temperature": 0.7, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=90).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_call(prompt, minlen=1500):
    models = [
        ("groq", "llama-3.3-70b-versatile"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("openrouter", "auto")
    ]
    for provider, model in models:
        try:
            log(f"🔄 Попытка: {provider} ({model})...")
            res = ai_groq(prompt) if provider == "groq" else ai_openrouter(prompt, model)
            if res and len(res) >= minlen:
                log(f"✅ Успех: {provider}, {len(res)} симв.")
                return res
            elif res:
                log(f"⚠️ {provider}: текст короткий ({len(res)} симв.)")
        except Exception as e:
            log(f"⚠️ {provider} ошибка: {e}")
    return None

# ============================================================
# ПАРСИНГ САЙТА
# ============================================================

def clean(s):
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def abs_url(u):
    u = (u or "").strip()
    if not u or u.startswith("data:"): return ""
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"): return SITE + u
    if u.startswith("http"): return u
    return ""

def brand_in_url(u):
    path = u.split("//", 1)[-1].split("/", 1)[-1].lower()
    return any(b in path for b in BRAND_SLUGS)

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
        log(f"⚠️ Sitemap недоступен: {e}")
        return []
    
    urls = sorted(set(urls))
    if len(urls) < 10:
        for s in CATEGORY_SEEDS:
            try:
                h = requests.get(s, timeout=20, headers=UA).text
                for href in re.findall(r'href=["\'](/catalog/[^"\']+)["\']', h):
                    u = abs_url(href)
                    if u and u not in urls: urls.append(u)
            except Exception: continue
        urls = sorted(set(urls))
    
    # Приоритет — ссылки с pavrus в адресе
    urls.sort(key=lambda u: (0 if brand_in_url(u) else 1))
    log(f"✅ Этап 1: найдено {len(urls)} ссылок каталога")
    return urls

def parse_page(html_text):
    """Извлекает H1, описание и характеристики со страницы товара."""
    # H1
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    if m: h1 = clean(m.group(1))
    
    # Мета-описание
    desc = ""
    dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_text, re.S | re.I)
    if dm: desc = clean(dm.group(1))
    
    # Основной контент (абзацы + характеристики)
    tail = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    
    # Убираем служебные блоки
    for mk in ["Назад к списку", "Нужна консультация", "Характеристики", "Описание"]:
        i = tail.find(mk)
        if i != -1: tail = tail[:i]
    
    chunks = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
    chunks += re.findall(r'<div[^>]+class=["\'][^"\']*(?:descr|text|detail)[^"\']*["\'][^>]*>(.*?)</div>', tail, re.S | re.I)
    
    raw = " ".join(clean(c) for c in chunks)
    keep = [s.strip() for s in raw.split(". ") if len(s.strip()) > 20 and "{" not in s]
    body = ". ".join(keep)[:2000]
    
    return h1, desc, body

def pick_page(urls, hist):
    """Выбирает случайную страницу, которой ещё не было."""
    avail = [u for u in urls if u not in hist] or urls
    page = random.choice(avail[:100])
    
    try:
        rs = requests.get(page, timeout=30, headers=UA)
        if rs.status_code != 200 or len(rs.text) < 3000:
            return None, "", "", ""
        r = rs.text
        
        h1, desc, body = parse_page(r)
        if not h1 or (len(body) + len(desc)) < 100:
            return None, "", "", ""
        
        log(f"✅ Этап 2: товар «{h1[:70]}» — {page}")
        return page, h1, desc, body
    except Exception as e:
        log(f"⚠️ Ошибка загрузки {page}: {e}")
        return None, "", "", ""

# ============================================================
# ГЕНЕРАЦИЯ СТАТЬИ И НОВОСТИ
# ============================================================

def generate_article(title, desc, body, url):
    """Генерирует структурированную статью с HTML-разметкой."""
    prompt = (
        f"Напиши развёрнутую статью о товаре Pavrus.\n\n"
        f"НАЗВАНИЕ: {title}\n"
        f"КРАТКОЕ ОПИСАНИЕ: {desc}\n"
        f"ДЕТАЛИ: {body[:1000]}\n"
        f"ССЫЛКА: {url}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Длина 1500-3000 символов.\n"
        f"3. Используй HTML-разметку: <h2> для основных разделов, <h3> для подразделов, <p> для текста.\n"
        f"4. Структура статьи:\n"
        f"   - <h2>Что это такое</h2> (введение, общее описание)\n"
        f"   - <h2>Назначение</h2> (для чего используется, где применяется)\n"
        f"   - <h2>Функциональные возможности</h2> (основные функции, характеристики)\n"
        f"   - <h2>Особенности</h2> (уникальные преимущества, отличия)\n"
        f"   - <h2>Рекомендации по использованию</h2> (как правильно применять)\n"
        f"   - <h2>Заключение</h2> (призыв обратиться к специалистам Pavrus)\n"
        f"5. Пиши как эксперт по профессиональному AV-оборудованию: живо, профессионально, без воды.\n"
        f"6. Подчеркни применение в конференц-залах, презентациях, мероприятиях.\n"
        f"7. В конце обязательно: «По всем вопросам обращайтесь к специалистам компании Pavrus».\n"
        f"8. НЕ добавляй внешних ссылок кроме {url}.\n"
    )
    
    article = ai_call(prompt, minlen=1500)
    if not article:
        log("⚠️ Не удалось сгенерировать статью — пробую короче")
        prompt_short = (
            f"Напиши статью о товаре Pavrus «{title}». "
            f"Описание: {desc}. Детали: {body[:500]}. "
            f"Требования: 1500-2500 символов, HTML-разметка (h2, h3, p), "
            f"структура: что это, назначение, возможности, особенности, рекомендации, "
            f"в конце призыв обратиться к специалистам Pavrus."
        )
        article = ai_call(prompt_short, minlen=1200)
    
    return article

def generate_news_from_article(article, title, url):
    """Создаёт новость на основе статьи (500-1000 символов)."""
    # Извлекаем основной текст без HTML-тегов для контекста
    plain_text = re.sub(r"<[^>]+>", " ", article).strip()
    
    prompt = (
        f"Создай краткую новость на основе статьи.\n\n"
        f"СТАТЬЯ: {plain_text[:1500]}\n"
        f"ТОВАР: {title}\n"
        f"ССЫЛКА: {url}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Длина СТРОГО 500-1000 символов.\n"
        f"3. Используй HTML-разметку: <h2> для заголовка, <p> для текста.\n"
        f"4. Структура: <h2>Заголовок</h2> + 2-3 абзаца <p>.\n"
        f"5. Сохрани суть статьи: что это, главное применение, ключевая особенность.\n"
        f"6. В конце: «Подробнее — у специалистов Pavrus».\n"
        f"7. Пиши живо, как новостной анонс.\n"
    )
    
    news = ai_call(prompt, minlen=400)
    if not news:
        # Если ИИ не справился, берём первые 800 символов статьи
        log("⚠️ Не удалось сгенерировать новость — ужимаю статью")
        news = article[:800].rsplit(".", 1)[0] + "."
        news = f"<h2>{title}</h2><p>{news}</p>"
    
    return news

# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================

def main():
    # Загрузка истории
    try:
        hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
    except Exception:
        hist = set()
    
    # Сбор URL
    urls = fetch_sitemap()
    if not urls:
        log(" Не удалось получить ссылки с сайта")
        sys.exit(1)
    
    # Выбор страницы
    page, title, desc, body = pick_page(urls, hist)
    if not page:
        log("❌ Не найдена подходящая страница")
        sys.exit(1)
    
    # Генерация статьи
    log(" Этап 3: генерация статьи...")
    article = generate_article(title, desc, body, page)
    if not article:
        log("❌ Не удалось сгенерировать статью")
        sys.exit(1)
    
    # Генерация новости
    log("📰 Этап 4: генерация новости...")
    news = generate_news_from_article(article, title, page)
    if not news:
        log("❌ Не удалось сгенерировать новость")
        sys.exit(1)
    
    # Сохранение истории
    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)
    
    # Вывод результатов
    log("=" * 50)
    log("✅ СТАТЬЯ:")
    log(article[:500] + ("..." if len(article) > 500 else ""))
    log(f"   Длина: {len(article)} симв.")
    log("=" * 50)
    log("✅ НОВОСТЬ:")
    log(news[:300] + ("..." if len(news) > 300 else ""))
    log(f"   Длина: {len(news)} симв.")
    log("=" * 50)
    log("✅ FINISH: статья и новость сгенерированы!")
    log("=" * 50)
    
    # Сохраняем в файлы для отправки
    output_dir = "articles_output"
    os.makedirs(output_dir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50]
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    
    with open(f"{output_dir}/{date_str}_{slug}_article.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body><h1>{title}</h1>{article}<p><a href='{page}'>Подробнее на сайте</a></p></body></html>")
    
    with open(f"{output_dir}/{date_str}_{slug}_news.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body>{news}<p><a href='{page}'>Подробнее</a></p></body></html>")
    
    with open(f"{output_dir}/{date_str}_{slug}_texts.txt", "w", encoding="utf-8") as f:
        f.write(f"ТОВАР: {title}\nССЫЛКА: {page}\n\n=== СТАТЬЯ ===\n{article}\n\n=== НОВОСТЬ ===\n{news}")
    
    log(f"💾 Файлы сохранены в папке {output_dir}/")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
