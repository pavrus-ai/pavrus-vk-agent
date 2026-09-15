# -*- coding: utf-8 -*-
import os, re, json, random, sys, time, datetime, requests, html, base64, uuid
from urllib.parse import urljoin
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)

try:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_OK = True
except ImportError:
    DOCX_OK = False
    print("⚠️ python-docx не установлен — DOCX не будет создан")

GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET", "").strip()

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "articles_history.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}

# ⚠️ СТРОГО только PAVRUS
BRAND_SLUG = "pavrus"

# Список мусора для очистки
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

log("Версия ℹ️ pavrus-articles-agent v5 (только GigaChat + DOCX + объёмная статья → новость)")

# ============================================================
# GigaChat: OAuth 2.0 + чат (с отключением SSL-проверки)
# ============================================================

_GIGACHAT_TOKEN = None
_GIGACHAT_TOKEN_EXPIRY = 0

def get_gigachat_token():
    """Получает токен GigaChat (действует 30 минут). Кэшируется в памяти."""
    global _GIGACHAT_TOKEN, _GIGACHAT_TOKEN_EXPIRY
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        return None
    if _GIGACHAT_TOKEN and time.time() < _GIGACHAT_TOKEN_EXPIRY:
        return _GIGACHAT_TOKEN
    try:
        credentials = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={"Authorization": f"Basic {credentials}",
                     "RqUID": str(uuid.uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"scope": "GIGACHAT_API_PERS"}, 
            timeout=30,
            verify=False)
        if "access_token" in r:
            _GIGACHAT_TOKEN = r["access_token"]
            _GIGACHAT_TOKEN_EXPIRY = time.time() + 1700
            log("✅ GigaChat: токен получен (действует 30 мин)")
            return _GIGACHAT_TOKEN
        log(f"️ GigaChat token error: {str(r)[:120]}")
    except Exception as e:
        log(f"⚠️ GigaChat auth error: {e}")
    return None

def ai_gigachat(prompt, minlen=1500):
    """GigaChat: генерация текста."""
    token = get_gigachat_token()
    if not token:
        return None
    try:
        r = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": "GigaChat:latest", "temperature": 0.7, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]}, 
            timeout=90, 
            verify=False)
        if "error" in r:
            log(f"️ GigaChat: {str(r['error'])[:120]}")
            return None
        res = r["choices"][0]["message"]["content"].strip()
        if len(res) >= minlen:
            log(f"✅ GigaChat: {len(res)} симв.")
            return res
        log(f"⚠️ GigaChat: текст короткий ({len(res)} симв., нужно {minlen})")
        return res if res else None
    except Exception as e:
        log(f"⚠️ GigaChat error: {e}")
        return None

# ============================================================
# ПАРСИНГ САЙТА (чистый)
# ============================================================

def clean(s):
    """Очищает текст от HTML и мусора."""
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    for pattern in JUNK_PATTERNS:
        s = re.sub(pattern, "", s, flags=re.IGNORECASE)
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
        log(f"⚠️ Sitemap недоступен: {e}")
        return []
    
    urls = sorted(set(urls))
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
    """Извлекает только полезный контент со страницы товара."""
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    if m: h1 = clean(m.group(1))
    
    desc = ""
    dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_text, re.S | re.I)
    if dm: desc = clean(dm.group(1))
    
    tail = html_text
    tail = re.sub(r"<script[^>]*>.*?</script>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<nav[^>]*>.*?</nav>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<header[^>]*>.*?</header>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<footer[^>]*>.*?</footer>", " ", tail, flags=re.S | re.I)
    
    desc_block = ""
    for cls in ["description", "descr", "detail", "product-description", "tab-content"]:
        m = re.search(rf'<div[^>]+class=["\'][^"\']*{cls}[^"\']*["\'][^>]*>(.*?)</div>', tail, re.S | re.I)
        if m:
            desc_block = m.group(1)
            break
    
    if not desc_block:
        chunks = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
        desc_block = " ".join(chunks)
    
    raw = clean(desc_block)
    sentences = raw.split(". ")
    keep = []
    for s in sentences:
        s = s.strip()
        if len(s) < 20: continue
        if "{" in s or "}" in s: continue
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
            log(f"⚠️ Страница {page}: мало текста")
            return None, "", "", ""
        
        log(f"✅ Этап 2: товар PAVRUS «{h1[:70]}» — {page}")
        log(f"   Описание: {desc[:100]}...")
        log(f"   Текст: {body[:100]}...")
        return page, h1, desc, body
    except Exception as e:
        log(f"️ Ошибка загрузки {page}: {e}")
        return None, "", "", ""

# ============================================================
# ГЕНЕРАЦИЯ СТАТЬИ (объёмный промпт)
# ============================================================

def generate_article(title, desc, body, url):
    """Генерирует объёмную статью через детальный промпт."""
    # ДЕТАЛЬНЫЙ ПРОМПТ для объёмной статьи
    prompt = (
        f"Напиши развёрнутую экспертную статью о профессиональном AV-оборудовании PAVRUS.\n\n"
        f"НАЗВАНИЕ ТОВАРА: {title}\n"
        f"КРАТКОЕ ОПИСАНИЕ: {desc}\n"
        f"ТЕХНИЧЕСКИЕ ХАРАКТЕРИСТИКИ: {body[:800]}\n"
        f"ССЫЛКА НА ТОВАР: {url}\n\n"
        f"ТРЕБОВАНИЯ К СТАТЬЕ:\n"
        f"1. Язык: ТОЛЬКО русский.\n"
        f"2. Длина: СТРОГО 1800-2500 символов (не меньше!).\n"
        f"3. Формат: HTML-разметка (<h2> для разделов, <p> для абзацев).\n"
        f"4. СТРУКТУРА (обязательно все разделы):\n"
        f"   <h2>Введение: что это за оборудование</h2>\n"
        f"   <p>2-3 абзаца: общее описание, место в линейке PAVRUS, для каких задач создано.</p>\n"
        f"   <h2>Технические характеристики и возможности</h2>\n"
        f"   <p>2-3 абзаца: подробно о ключевых параметрах, что они дают на практике.</p>\n"
        f"   <h2>Сферы применения</h2>\n"
        f"   <p>2 абзаца: конференц-залы, корпоративные мероприятия, образовательные учреждения, театры, студии.</p>\n"
        f"   <h2>Ключевые преимущества</h2>\n"
        f"   <p>2 абзаца: чем отличается от аналогов, надёжность, удобство использования.</p>\n"
        f"   <h2>Рекомендации по использованию</h2>\n"
        f"   <p>1-2 абзаца: советы по установке, настройке, эксплуатации.</p>\n"
        f"   <h2>Заключение</h2>\n"
        f"   <p>1 абзац: итог + призыв обратиться к специалистам PAVRUS.</p>\n"
        f"5. СТИЛЬ: профессиональный, но живой. Пиши как эксперт по AV-оборудованию с 10-летним опытом.\n"
        f"6. НЕ используй слова «инновационный», «революционный», «уникальный» без конкретики.\n"
        f"7. НЕ добавляй внешних ссылок кроме {url}.\n"
        f"8. В последнем абзаце обязательно: «По всем вопросам обращайтесь к специалистам компании PAVRUS».\n"
    )
    
    article = ai_gigachat(prompt, minlen=1500)
    if article:
        return article
    
    # Если GigaChat не справился — пробуем упрощённый промпт
    log("⚠️ Не удалось создать объёмную статью — пробую упрощённую версию")
    prompt_short = (
        f"Напиши статью о товаре PAVRUS «{title}».\n"
        f"Описание: {desc}\n"
        f"Характеристики: {body[:500]}\n\n"
        f"Требования: 1500-2000 символов, HTML-разметка (h2, p), "
        f"структура: что это, характеристики, применение, преимущества, рекомендации. "
        f"В конце призыв обратиться к специалистам PAVRUS."
    )
    
    article = ai_gigachat(prompt_short, minlen=1200)
    if article:
        return article
    
    # Полный фолбэк
    log("⚠️ GigaChat недоступен — создаю минимальную статью из данных")
    return f"""<h2>{title}</h2>
<p>{desc if desc else 'Профессиональное AV-оборудование PAVRUS.'}</p>
<h2>Применение</h2>
<p>Используется в конференц-залах, на мероприятиях и презентациях.</p>
<h2>Особенности</h2>
<p>{body[:300] if body else 'Высокое качество и надёжность.'}</p>
<p>По вопросам обращайтесь к специалистам PAVRUS.</p>"""

# ============================================================
# ГЕНЕРАЦИЯ НОВОСТИ (сжатие статьи)
# ============================================================

def generate_news_from_article(article, title, url):
    """Создаёт краткую новость на основе статьи."""
    # Извлекаем чистый текст
    plain_text = re.sub(r"<[^>]+>", " ", article).strip()
    plain_text = re.sub(r"\s+", " ", plain_text)
    
    prompt = (
        f"Создай краткую новость на основе статьи о товаре PAVRUS.\n\n"
        f"ИСХОДНАЯ СТАТЬЯ:\n{plain_text[:2000]}\n\n"
        f"НАЗВАНИЕ ТОВАРА: {title}\n"
        f"ССЫЛКА: {url}\n\n"
        f"ТРЕБОВАНИЯ К НОВОСТИ:\n"
        f"1. Язык: ТОЛЬКО русский.\n"
        f"2. Длина: СТРОГО 500-700 символов.\n"
        f"3. Формат: HTML-разметка (<h2> заголовок, <p> абзацы).\n"
        f"4. Структура:\n"
        f"   <h2>Краткий заголовок</h2>\n"
        f"   <p>1 абзац: что это за товар и его главное назначение.</p>\n"
        f"   <p>1 абзац: ключевая особенность или преимущество.</p>\n"
        f"   <p>1 абзац: призыв к действию.</p>\n"
        f"5. Сохрани суть: что это, главное применение, ключевая особенность.\n"
        f"6. В конце: «Подробнее — у специалистов PAVRUS».\n"
        f"7. Пиши живо, как новостной анонс для сайта компании.\n"
    )
    
    news = ai_gigachat(prompt, minlen=400)
    if news:
        return news
    
    # Фолбэк: берём первые 600 символов статьи
    log("⚠️ Не удалось сгенерировать новость — сжимаю статью")
    short = plain_text[:600].rsplit(".", 1)[0] + "."
    return f"<h2>{title}</h2><p>{short}</p><p>Подробнее у специалистов PAVRUS.</p>"

# ============================================================
# СОЗДАНИЕ DOCX
# ============================================================

def create_docx(title, article, news, url, date_str, slug):
    """Создаёт DOCX файл со статьёй и новостью."""
    if not DOCX_OK:
        log("⚠️ python-docx не установлен — пропускаю создание DOCX")
        return None
    
    doc = Document()
    
    # Заголовок документа
    doc.add_heading(f'PAVRUS: {title}', 0)
    doc.add_paragraph(f'Дата: {date_str}', style='Intense Quote')
    doc.add_paragraph(f'Ссылка на товар: {url}', style='Intense Quote')
    doc.add_paragraph()
    
    # Статья
    doc.add_heading('СТАТЬЯ', 1)
    
    # Парсим HTML статьи
    article_plain = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n\1\n", article)
    article_plain = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n\1\n", article_plain)
    article_plain = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", article_plain)
    article_plain = re.sub(r"<[^>]+>", "", article_plain)
    article_plain = re.sub(r"\n+", "\n", article_plain).strip()
    
    for line in article_plain.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Если строка похожа на заголовок (короткая, без точки в конце)
        if len(line) < 100 and not line.endswith('.') and not line.endswith(','):
            doc.add_heading(line, 2)
        else:
            doc.add_paragraph(line)
    
    doc.add_page_break()
    
    # Новость
    doc.add_heading('НОВОСТЬ', 1)
    
    news_plain = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n\1\n", news)
    news_plain = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", news_plain)
    news_plain = re.sub(r"<[^>]+>", "", news_plain)
    news_plain = re.sub(r"\n+", "\n", news_plain).strip()
    
    for line in news_plain.split('\n'):
        line = line.strip()
        if not line:
            continue
        if len(line) < 100 and not line.endswith('.') and not line.endswith(','):
            doc.add_heading(line, 2)
        else:
            doc.add_paragraph(line)
    
    # Сохраняем
    output_dir = "articles_output"
    os.makedirs(output_dir, exist_ok=True)
    docx_path = f"{output_dir}/{date_str}_{slug}.docx"
    doc.save(docx_path)
    log(f"✅ DOCX создан: {docx_path}")
    return docx_path

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
    
    log("📝 Этап 3: генерация объёмной статьи (1500-2500 симв.)...")
    article = generate_article(title, desc, body, page)
    if not article:
        log("❌ Не удалось сгенерировать статью")
        sys.exit(1)
    
    log("📰 Этап 4: генерация новости (500-700 симв.)...")
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
    
    # Сохраняем файлы
    output_dir = "articles_output"
    os.makedirs(output_dir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50]
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # HTML файлы
    with open(f"{output_dir}/{date_str}_{slug}_article.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body><h1>{title} (PAVRUS)</h1>{article}<p><a href='{page}'>Подробнее на сайте</a></p></body></html>")
    
    with open(f"{output_dir}/{date_str}_{slug}_news.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body>{news}<p><a href='{page}'>Подробнее</a></p></body></html>")
    
    # Текстовый файл
    with open(f"{output_dir}/{date_str}_{slug}_texts.txt", "w", encoding="utf-8") as f:
        f.write(f"ТОВАР PAVRUS: {title}\nССЫЛКА: {page}\n\n=== СТАТЬЯ ===\n{article}\n\n=== НОВОСТЬ ===\n{news}")
    
    # DOCX файл
    create_docx(title, article, news, page, date_str, slug)
    
    log(f"💾 Файлы сохранены в папке {output_dir}/")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
