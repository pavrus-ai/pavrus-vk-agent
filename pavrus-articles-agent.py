# -*- coding: utf-8 -*-
import os, re, json, random, sys, time, datetime, requests, html
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

# ⚠️ СТРОГО только PAVRUS — никаких htdz/chartu/restmoment
BRAND_SLUG = "pavrus"

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

log("Версия ℹ️ pavrus-articles-agent v2 (СТРОГО бренд PAVRUS + статья + новость с HTML-разметкой)")

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

def ai_call(prompt, minlen=1500):
    if not GH_AI_TOKEN:
        log("⚠️ github-models: GITHUB_TOKEN не передан")
    else:
        log("🔄 Попытка: github-models (gpt-4o-mini)...")
        res = ai_github(prompt)
        if res and len(res) >= minlen:
            log(f"✅ Успех: github-models, {len(res)} симв.")
            return res
    if not CEREBRAS_KEY:
        log("⚠️ cerebras: CEREBRAS_KEY не передан")
    else:
        log(" Попытка: cerebras (llama-3.3-70b)...")
        res = ai_cerebras(prompt)
        if res and len(res) >= minlen:
            log(f"✅ Успех: cerebras, {len(res)} симв.")
            return res
    if not MISTRAL_KEY:
        log("⚠️ mistral: MISTRAL_KEY не передан")
    else:
        log("🔄 Попытка: mistral (mistral-small)...")
        res = ai_mistral(prompt)
        if res and len(res) >= minlen:
            log(f"✅ Успех: mistral, {len(res)} симв.")
            return res
    for i, key in enumerate((GROQ_KEY, GROQ_KEY2)):
        if not key: continue
        log(f"🔄 Попытка: groq (ключ {i+1})...")
        res = ai_groq(prompt, key)
        if res and len(res) >= minlen:
            log(f"✅ Успех: groq (ключ {i+1}), {len(res)} симв.")
            return res
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

def is_pavrus_brand(u):
    """СТРОГО: только товары бренда PAVRUS (не htdz/chartu/restmoment)."""
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
        log(f"⚠️ Sitemap недоступен: {e}")
        return []
    
    urls = sorted(set(urls))
    
    # ⚠️ ФИЛЬТР: оставляем ТОЛЬКО товары PAVRUS
    pavrus_urls = [u for u in urls if is_pavrus_brand(u)]
    log(f"ℹ️ Этап 1: всего ссылок /catalog/: {len(urls)}")
    log(f" После фильтра по бренду PAVRUS: {len(pavrus_urls)} ссылок")
    
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
        log(f"🎯 После обхода разделов: {len(pavrus_urls)} ссылок PAVRUS")
    
    if not pavrus_urls:
        raise RuntimeError("Нет ссылок на товары PAVRUS")
    return pavrus_urls

def parse_page(html_text):
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    if m: h1 = clean(m.group(1))
    
    desc = ""
    dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_text, re.S | re.I)
    if dm: desc = clean(dm.group(1))
    
    tail = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    
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
    """Выбирает случайную страницу PAVRUS, которой ещё не было."""
    avail = [u for u in urls if u not in hist] or urls
    page = random.choice(avail)
    
    try:
        rs = requests.get(page, timeout=30, headers=UA)
        if rs.status_code != 200 or len(rs.text) < 3000:
            return None, "", "", ""
        r = rs.text
        
        h1, desc, body = parse_page(r)
        if not h1 or (len(body) + len(desc)) < 100:
            return None, "", "", ""
        
        log(f"✅ Этап 2: товар PAVRUS «{h1[:70]}» — {page}")
        return page, h1, desc, body
    except Exception as e:
        log(f"⚠️ Ошибка загрузки {page}: {e}")
        return None, "", "", ""

# ============================================================
# ГЕНЕРАЦИЯ СТАТЬИ И НОВОСТИ
# ============================================================

def generate_article(title, desc, body, url):
    prompt = (
        f"Напиши развёрнутую статью о товаре PAVRUS.\n\n"
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
        f"   - <h2>Заключение</h2> (призыв обратиться к специалистам PAVRUS)\n"
        f"5. Пиши как эксперт по профессиональному AV-оборудованию: живо, профессионально, без воды.\n"
        f"6. Подчеркни применение в конференц-залах, презентациях, мероприятиях.\n"
        f"7. В конце обязательно: «По всем вопросам обращайтесь к специалистам компании PAVRUS».\n"
        f"8. НЕ добавляй внешних ссылок кроме {url}.\n"
    )
    
    article = ai_call(prompt, minlen=1500)
    if not article:
        log("⚠️ Не удалось сгенерировать статью — пробую короче")
        prompt_short = (
            f"Напиши статью о товаре PAVRUS «{title}». "
            f"Описание: {desc}. Детали: {body[:500]}. "
            f"Требования: 1500-2500 символов, HTML-разметка (h2, h3, p), "
            f"структура: что это, назначение, возможности, особенности, рекомендации, "
            f"в конце призыв обратиться к специалистам PAVRUS."
        )
        article = ai_call(prompt_short, minlen=1200)
    
    return article

def generate_news_from_article(article, title, url):
    plain_text = re.sub(r"<[^>]+>", " ", article).strip()
    
    prompt = (
        f"Создай краткую новость на основе статьи.\n\n"
        f"СТАТЬЯ: {plain_text[:1500]}\n"
        f"ТОВАР PAVRUS: {title}\n"
        f"ССЫЛКА: {url}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Длина СТРОГО 500-1000 символов.\n"
        f"3. Используй HTML-разметку: <h2> для заголовка, <p> для текста.\n"
        f"4. Структура: <h2>Заголовок</h2> + 2-3 абзаца <p>.\n"
        f"5. Сохрани суть статьи: что это, главное применение, ключевая особенность.\n"
        f"6. В конце: «Подробнее — у специалистов PAVRUS».\n"
        f"7. Пиши живо, как новостной анонс.\n"
    )
    
    news = ai_call(prompt, minlen=400)
    if not news:
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
    
    # Сбор URL (ТОЛЬКО PAVRUS)
    urls = fetch_sitemap()
    if not urls:
        log("❌ Не удалось получить ссылки PAVRUS с сайта")
        sys.exit(1)
    
    # Выбор страницы
    page, title, desc, body = pick_page(urls, hist)
    if not page:
        log("❌ Не найдена подходящая страница PAVRUS")
        sys.exit(1)
    
    # Генерация статьи
    log(" Этап 3: генерация статьи (1500-3000 симв.)...")
    article = generate_article(title, desc, body, page)
    if not article:
        log("❌ Не удалось сгенерировать статью")
        sys.exit(1)
    
    # Генерация новости
    log("📰 Этап 4: генерация новости (500-1000 симв.)...")
    news = generate_news_from_article(article, title, page)
    if not news:
        log(" Не удалось сгенерировать новость")
        sys.exit(1)
    
    # Сохранение истории
    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)
    
    # Вывод результатов
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
    
    # Сохраняем в файлы
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
