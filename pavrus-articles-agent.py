# -*- coding: utf-8 -*-
import os, re, json, random, sys, time, datetime, requests, html, base64, uuid
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)

try:
    from docx import Document
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET", "").strip()
GIGACHAT_SCOPE = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip()
GIGACHAT_MODEL = os.environ.get("GIGACHAT_MODEL", "GigaChat-Pro").strip()

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "articles_history.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}

# ⚠️ СТРОГО только бренд PAVRUS
BRAND_SLUG = "pavrus"

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

log("Версия ℹ️ pavrus-articles-agent v7 (только GigaChat OAuth: Client ID + Secret + Scope; статья 1500-2000 → новость 500-700; DOCX; без мусорных фолбэков)")

# ============================================================
# GigaChat: OAuth 2.0 + чат
# ============================================================

_GIGACHAT_TOKEN = None
_GIGACHAT_TOKEN_EXPIRY = 0

def get_gigachat_token():
    """OAuth-токен GigaChat (30 мин). Кэш в памяти + полная диагностика."""
    global _GIGACHAT_TOKEN, _GIGACHAT_TOKEN_EXPIRY
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        log("⚠️ GigaChat: GIGACHAT_CLIENT_ID / GIGACHAT_CLIENT_SECRET не заданы")
        return None
    if _GIGACHAT_TOKEN and time.time() < _GIGACHAT_TOKEN_EXPIRY:
        return _GIGACHAT_TOKEN
    try:
        credentials = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={"Authorization": f"Basic {credentials}",
                     "RqUID": str(uuid.uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"scope": GIGACHAT_SCOPE},
            timeout=30, verify=False)
        log(f"ℹ️ GigaChat OAuth: статус {r.status_code} (scope={GIGACHAT_SCOPE})")
        if r.status_code != 200:
            log(f"⚠️ GigaChat OAuth тело: {r.text[:300]}")
            return None
        j = r.json()
        if "access_token" in j:
            _GIGACHAT_TOKEN = j["access_token"]
            _GIGACHAT_TOKEN_EXPIRY = time.time() + 1700
            log("✅ GigaChat: токен получен (действует 30 мин)")
            return _GIGACHAT_TOKEN
        log(f"⚠️ GigaChat OAuth: нет access_token в ответе: {str(j)[:200]}")
    except Exception as e:
        log(f"⚠️ GigaChat auth error: {e}")
    return None

def gigachat_chat(prompt, model):
    """Один запрос к GigaChat указанной моделью."""
    token = get_gigachat_token()
    if not token:
        return None
    try:
        r = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": model, "temperature": 0.7, "max_tokens": 4000,
                  "messages": [{"role": "user",
                                "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
            timeout=120, verify=False)
        if r.status_code != 200:
            log(f"⚠️ GigaChat chat [{model}]: статус {r.status_code}: {r.text[:200]}")
            return None
        res = r.json()["choices"][0]["message"]["content"].strip()
        log(f"✅ GigaChat [{model}]: ответ {len(res)} симв.")
        return res
    except Exception as e:
        log(f"⚠️ GigaChat chat [{model}] error: {e}")
        return None

def ai_gigachat(prompt, minlen):
    """Пробуем модели по очереди: GIGACHAT_MODEL → GigaChat:latest."""
    models = [GIGACHAT_MODEL, "GigaChat:latest"]
    seen = set()
    for mdl in models:
        if not mdl or mdl in seen:
            continue
        seen.add(mdl)
        log(f"🔄 Попытка: gigachat ({mdl})...")
        res = gigachat_chat(prompt, mdl)
        if res and len(res) >= minlen:
            return res
        if res:
            log(f"⚠️ GigaChat [{mdl}]: коротко ({len(res)} симв., нужно ≥{minlen})")
    return None

# ============================================================
# ПАРСИНГ САЙТА (чистый, только данные для промпта)
# ============================================================

def clean(s):
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    for pattern in JUNK_PATTERNS:
        s = re.sub(pattern, "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()

def abs_url(u):
    u = (u or "").strip()
    if not u or u.startswith("data:"): return ""
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"): return SITE + u
    if u.startswith("http"): return u
    return ""

def is_pavrus_brand(u):
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
            except Exception:
                continue
    except Exception as e:
        log(f"⚠️ Sitemap недоступен: {e}")
        return []
    urls = sorted(set(urls))
    pavrus_urls = [u for u in urls if is_pavrus_brand(u)]
    log(f"ℹ️ Этап 1: всего /catalog/: {len(urls)}; после фильтра PAVRUS: {len(pavrus_urls)}")
    if len(pavrus_urls) < 10:
        for s in CATEGORY_SEEDS:
            try:
                h = requests.get(s, timeout=20, headers=UA).text
                for href in re.findall(r'href=["\'](/catalog/[^"\']+)["\']', h):
                    u = abs_url(href)
                    if u and u not in pavrus_urls and is_pavrus_brand(u):
                        pavrus_urls.append(u)
            except Exception:
                continue
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
        desc_block = " ".join(re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I))
    raw = clean(desc_block)
    keep = [s.strip() for s in raw.split(". ")
            if len(s.strip()) > 20 and "{" not in s
            and not any(j in s.lower() for j in ["корзин", "кабинет", "войти", "каталог", "контакты"])]
    return h1, desc, ". ".join(keep)[:1500]

def pick_page(urls, hist):
    avail = [u for u in urls if u not in hist] or urls
    for attempt in range(8):
        page = random.choice(avail)
        try:
            rs = requests.get(page, timeout=30, headers=UA)
            if rs.status_code != 200 or len(rs.text) < 3000:
                continue
            h1, desc, body = parse_page(rs.text)
            if not h1 or (len(body) + len(desc)) < 50:
                log(f"⚠️ Попытка {attempt+1}: мало текста — {page}")
                continue
            log(f"✅ Этап 2: товар PAVRUS «{h1[:70]}» — {page}")
            log(f"   Описание: {desc[:100]}")
            return page, h1, desc, body
        except Exception as e:
            log(f"⚠️ Попытка {attempt+1} ошибка: {e}")
    return None, "", "", ""

# ============================================================
# ГЕНЕРАЦИЯ СТАТЬИ (объёмный промпт) И НОВОСТИ (сжатие)
# ============================================================

def generate_article(title, desc, body, url):
    prompt = (
        f"Напиши развёрнутую экспертную статью о профессиональном AV-оборудовании PAVRUS.\n\n"
        f"НАЗВАНИЕ ТОВАРА: {title}\n"
        f"КРАТКОЕ ОПИСАНИЕ: {desc}\n"
        f"ТЕХНИЧЕСКИЕ ХАРАКТЕРИСТИКИ: {body[:800]}\n"
        f"ССЫЛКА НА ТОВАР: {url}\n\n"
        f"ТРЕБОВАНИЯ К СТАТЬЕ:\n"
        f"1. Язык: ТОЛЬКО русский.\n"
        f"2. Длина: СТРОГО 1500-2000 символов.\n"
        f"3. Формат: HTML-разметка (<h2> для разделов, <h3> для подразделов, <p> для абзацев).\n"
        f"4. СТРУКТУРА (все разделы обязательны):\n"
        f"   <h2>Что это такое</h2> — 1-2 абзаца: общее описание, место в линейке PAVRUS.\n"
        f"   <h2>Назначение</h2> — 1-2 абзаца: для каких задач и объектов создано.\n"
        f"   <h2>Функциональные возможности</h2> — 2 абзаца: ключевые параметры и что они дают на практике.\n"
        f"   <h2>Особенности</h2> — 1-2 абзаца: отличия от аналогов, надёжность.\n"
        f"   <h2>Рекомендации по использованию</h2> — 1 абзац: установка, настройка, эксплуатация.\n"
        f"   <h2>Заключение</h2> — 1 абзац: итог.\n"
        f"5. Стиль: эксперт по AV-оборудованию, живо и конкретно, без воды и штампов.\n"
        f"6. Не выдумывай характеристики, которых нет в исходных данных.\n"
        f"7. В заключении обязательно: «По всем вопросам обращайтесь к специалистам компании PAVRUS».\n"
    )
    article = ai_gigachat(prompt, minlen=1500)
    if article:
        return article
    log("⚠️ Объёмная статья не получилась — вторая попытка с упрощённым промптом")
    prompt2 = (
        f"Статья о товаре PAVRUS «{title}». Описание: {desc}. Характеристики: {body[:500]}.\n"
        f"1500-2000 символов, HTML (<h2>, <p>). Разделы: что это, назначение, возможности, "
        f"особенности, рекомендации, заключение с фразой «По всем вопросам обращайтесь к специалистам компании PAVRUS»."
    )
    return ai_gigachat(prompt2, minlen=1500)

def generate_news_from_article(article, title, url):
    plain = re.sub(r"<[^>]+>", " ", article)
    plain = re.sub(r"\s+", " ", plain).strip()
    prompt = (
        f"Сожми статью в короткую новость.\n\nСТАТЬЯ:\n{plain[:1800]}\n\n"
        f"ТОВАР: {title}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Длина СТРОГО 500-700 символов.\n"
        f"3. Формат: <h2>Заголовок</h2> + 2-3 абзаца <p>.\n"
        f"4. Содержание: что за товар, главное применение, ключевая особенность.\n"
        f"5. В конце: «Подробнее — у специалистов PAVRUS».\n"
        f"6. Стиль: живой новостной анонс.\n"
    )
    news = ai_gigachat(prompt, minlen=450)
    if news:
        if len(news) > 800:
            news = news[:800].rsplit(".", 1)[0] + "."
        return news
    log("⚠️ Новость не сжалась — беру первые предложения статьи")
    sentences = plain.split(". ")
    out = []
    for s in sentences:
        out.append(s.strip() + ".")
        if len(". ".join(out)) > 550:
            break
    return f"<h2>{title}</h2><p>{'. '.join(out)}</p><p>Подробнее — у специалистов PAVRUS.</p>"

# ============================================================
# DOCX
# ============================================================

def html_to_lines(text):
    t = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.S | re.I)
    t = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", t, flags=re.S | re.I)
    t = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return [l.strip() for l in t.split("\n") if l.strip()]

def create_docx(title, article, news, url, date_str, slug):
    if not DOCX_OK:
        log("⚠️ python-docx не установлен — DOCX пропущен")
        return None
    doc = Document()
    doc.add_heading(f"PAVRUS: {title}", 0)
    doc.add_paragraph(f"Дата: {date_str} | Ссылка: {url}")
    doc.add_heading("СТАТЬЯ", 1)
    for line in html_to_lines(article):
        if line.startswith("### "):
            doc.add_heading(line[4:], 3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], 2)
        else:
            doc.add_paragraph(line)
    doc.add_page_break()
    doc.add_heading("НОВОСТЬ", 1)
    for line in html_to_lines(news):
        if line.startswith("### "):
            doc.add_heading(line[4:], 3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], 2)
        else:
            doc.add_paragraph(line)
    os.makedirs("articles_output", exist_ok=True)
    path = f"articles_output/{date_str}_{slug}.docx"
    doc.save(path)
    log(f"✅ DOCX создан: {path}")
    return path

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
        log("❌ Не удалось получить ссылки PAVRUS")
        sys.exit(1)

    page, title, desc, body = pick_page(urls, hist)
    if not page:
        log("❌ Не найдена подходящая страница PAVRUS")
        sys.exit(1)

    log("📝 Этап 3: генерация статьи (1500-2000 симв.)...")
    article = generate_article(title, desc, body, page)
    if not article:
        log("❌ GigaChat не смог написать статью — выход без мусорного фолбэка")
        sys.exit(1)

    log("📰 Этап 4: генерация новости (500-700 симв.)...")
    news = generate_news_from_article(article, title, page)
    if not news:
        log("❌ Новость не создана — выход")
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

    output_dir = "articles_output"
    os.makedirs(output_dir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50]
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    with open(f"{output_dir}/{date_str}_{slug}_article.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body><h1>{title} (PAVRUS)</h1>{article}"
                f"<p><a href='{page}'>Подробнее на сайте</a></p></body></html>")

    with open(f"{output_dir}/{date_str}_{slug}_news.html", "w", encoding="utf-8") as f:
        f.write(f"<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'><title>{title}</title></head>"
                f"<body>{news}<p><a href='{page}'>Подробнее</a></p></body></html>")

    with open(f"{output_dir}/{date_str}_{slug}_texts.txt", "w", encoding="utf-8") as f:
        f.write(f"ТОВАР PAVRUS: {title}\nССЫЛКА: {page}\n\n=== СТАТЬЯ ===\n{article}\n\n=== НОВОСТЬ ===\n{news}")

    create_docx(title, article, news, page, date_str, slug)

    log("✅ FINISH: статья + новость + DOCX готовы к ручной публикации!")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
