# -*- coding: utf-8 -*-
import os, re, json, random, sys, time, datetime, requests, html, base64, uuid, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning
warnings.simplefilter('ignore', InsecureRequestWarning)

try:
    from docx import Document
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

# ============================================================
# КОНФИГУРАЦИЯ (ВСЕ ПРОБЕЛЫ УДАЛЕНЫ)
# ============================================================
GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET", "").strip()
GIGACHAT_SCOPE = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip()
GIGACHAT_MODEL = os.environ.get("GIGACHAT_MODEL", "GigaChat-Pro").strip()

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = os.environ.get("SMTP_PORT", "587").strip()
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
EMAIL_TO = os.environ.get("EMAIL_TO", "").strip()

SITE = "https://pavrus.ru"
HISTORY = "articles_history.json"
CACHE = "sitemap_cache.json"

BRAND_SLUG = "pavrus"

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F\u2B00-\u2BFF\uFE0F]",
    flags=re.UNICODE)

JUNK_PATTERNS = [
    r"Санкт-Петербург|Москва|Новосибирск|Краснодар|Красноярск",
    r"Войти|Выйти|Регистрация|Личный кабинет",
    r"Каталог|Компания|Информация|Контакты|Доставка|Оплата",
    r"Заказать звонок|Обратная связь|Назад к списку",
    r"Выбрать автоматически|Ваш город",
    r"8 \(800|info@|показать еще",
    r"корзин|кабинет|избранн|сравнени",
]

# 🛡️ АНТИ-НЕЙРОСЛОП: список запрещенных ИИ-клише и их замен
ANTI_SLOP_REPLACEMENTS = {
    "представляет собой": "",
    "является": "",
    "стоит отметить": "",
    "важно понимать": "",
    "безусловно": "",
    "в современном мире": "",
    "играет ключевую роль": "",
    "инновационный": "современный",
    "революционный": "новый",
    "подводя итог": "",
    "в заключение": "",
    "таким образом": "",
    "не стоит забывать": "",
    "следует отметить": ""
}

def clean_slop(text):
    """Вычищает ИИ-клише из текста"""
    for slop, replacement in ANTI_SLOP_REPLACEMENTS.items():
        text = re.sub(r"\b" + slop + r"\b", replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()

HEADING_SEEDS = {
    "what_is": ["Что представляет собой устройство", "Принцип работы устройства",
                "Техническая справка", "Общее описание", "Анатомия решения",
                "Знакомство с устройством", "Главное о продукте", "Для чего создано устройство"],
    "purpose": ["Сценарии применения", "Место в AV-инсталляции", "Роль и задачи устройства",
                "Области интеграции", "Целевые объекты", "Для кого создано это решение",
                "Ищем точку приложения", "Практическое применение"],
    "features": ["Матрица технических характеристик", "Функциональные возможности",
                 "Варианты подключения и интерфейсы", "Полный разбор возможностей",
                 "Логика работы решения", "Полезный функционал", "Ключевые возможности",
                 "Технические особенности"],
    "advantages": ["Конструктивные преимущества", "Отличительные инженерные решения",
                   "Почему эта модель выигрывает", "Схемотехника и надежность",
                   "Конкурентные отличия", "Важнейшие детали устройства",
                   "Преимущественные фишки", "Уникальные технологии"],
    "usage": ["Рекомендации по использованию", "Требования к монтажу",
              "Особенности эксплуатации", "Практические советы", "Лайфхаки по применению",
              "Быстрый старт", "Настраиваем устройство", "Способы инсталляции"],
    "conclusion": ["Технические выводы", "Экспертное заключение", "Реальное применение",
                   "Устройство стоит своих денег", "Честный вердикт",
                   "Переход на новый уровень", "Следующий шаг клиента",
                   "Эффективность применения"],
}

def select_seeds():
    return {k: random.choice(v) for k, v in HEADING_SEEDS.items()}

def log(msg):
    print(msg, flush=True)

log("pavrus-articles-agent v17 (Playwright, локальный кэш, строгая очистка, АНТИ-НЕЙРОСЛОП)")

# ============================================================
# PLAYWRIGHT: обход JS-защиты Beget
# ============================================================
_pw_browser = None
_pw_context = None

def pw_init():
    global _pw_browser, _pw_context
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _pw_browser = pw.chromium.launch(headless=True)
        _pw_context = _pw_browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="ru-RU"
        )
        log("Playwright Chromium запущен")
        return True
    except Exception as e:
        log(f"Playwright недоступен: {e}")
        return False

def pw_get_page(url):
    if not _pw_context:
        return None
    try:
        page = _pw_context.new_page()
        page.goto(url, timeout=30000, wait_until="networkidle")
        content = page.content()
        page.close()
        log(f"Playwright GET {url} -> {len(content)} байт")
        return content
    except Exception as e:
        log(f"Playwright ошибка: {url} -> {e}")
        return None

def pw_close():
    global _pw_browser, _pw_context
    try:
        if _pw_browser:
            _pw_browser.close()
    except Exception:
        pass

# ============================================================
# GIGACHAT
# ============================================================
_GIGACHAT_TOKEN = None
_GIGACHAT_TOKEN_EXPIRY = 0

def get_gigachat_token():
    global _GIGACHAT_TOKEN, _GIGACHAT_TOKEN_EXPIRY
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        log("GigaChat: ключи не заданы")
        return None
    if _GIGACHAT_TOKEN and time.time() < _GIGACHAT_TOKEN_EXPIRY:
        return _GIGACHAT_TOKEN
    try:
        credentials = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={"Authorization": f"Basic {credentials}",
                     "RqUID": str(uuid.uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"scope": GIGACHAT_SCOPE}, timeout=30, verify=False)
        log(f"GigaChat OAuth: статус {r.status_code}")
        if r.status_code != 200:
            log(f"GigaChat OAuth тело: {r.text[:300]}")
            return None
        j = r.json()
        if "access_token" in j:
            _GIGACHAT_TOKEN = j["access_token"]
            _GIGACHAT_TOKEN_EXPIRY = time.time() + 1700
            log("GigaChat: токен получен (30 мин)")
            return _GIGACHAT_TOKEN
    except Exception as e:
        log(f"GigaChat auth error: {e}")
    return None

def gigachat_chat(prompt, model):
    token = get_gigachat_token()
    if not token:
        return None
    for attempt in range(2):
        try:
            r = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"model": model, "temperature": 0.7, "max_tokens": 4000,
                      "messages": [{"role": "user",
                                    "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
                timeout=120, verify=False)
            if r.status_code != 200:
                log(f"GigaChat chat [{model}]: статус {r.status_code}: {r.text[:200]}")
                return None
            res = r.json()["choices"][0]["message"]["content"].strip()
            log(f"GigaChat [{model}]: ответ {len(res)} симв.")
            return res
        except Exception as e:
            log(f"GigaChat [{model}] попытка {attempt+1}: {str(e)[:150]}")
            if attempt == 0:
                log("Пауза 10 сек и повтор...")
                time.sleep(10)
    return None

def ai_gigachat(prompt, minlen):
    models = [GIGACHAT_MODEL, "GigaChat:latest"]
    seen = set()
    for mdl in models:
        if not mdl or mdl in seen:
            continue
        seen.add(mdl)
        log(f"Попытка: gigachat ({mdl})...")
        res = gigachat_chat(prompt, mdl)
        if res and len(res) >= minlen:
            return res
        if res:
            log(f"GigaChat [{mdl}]: коротко ({len(res)} симв., нужно >={minlen})")
    return None

# ============================================================
# САНИТИЗАЦИЯ И ОБРЕЗКА
# ============================================================
def sanitize_ai_html(text):
    t = text.replace("`html", "").replace("`", "")
    t = re.sub(r"^#{1,2}\s*(.+)$", r"<h2>\1</h2>", t, flags=re.M)
    t = re.sub(r"^#{3,6}\s*(.+)$", r"<h3>\1</h3>", t, flags=re.M)
    t = re.sub(r"<(h[1-4])[^>]*>", r"<\1>", t, flags=re.I)
    t = t.replace("**", "").replace("__", "")
    t = EMOJI_RE.sub("", t)
    parts = re.split(r"(<h[23]>.*?</h[23]>)", t, flags=re.S)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p.startswith("<h2>") or p.startswith("<h3>"):
            out.append(p)
        else:
            p = re.sub(r"</?p[^>]*>", "\n", p)
            for chunk in p.split("\n"):
                chunk = " ".join(chunk.split())
                if len(chunk) > 3:
                    out.append(f"<p>{chunk}</p>")
    if out and out[0].startswith("<h2>"):
        low = out[0].lower()
        if "статья" in low or "эксперт" in low or "обзор" in low:
            out = out[1:]
    return "\n".join(out)

def trim_article(article, max_len=2600):
    if len(article) <= max_len:
        return article
    sections = re.split(r"(?=<h2>)", article)
    if len(sections) <= 2:
        cut = article[:max_len]
        i = cut.rfind("</p>")
        return cut[:i+4] if i != -1 else cut
    first, last = sections[0], sections[-1]
    middle = sections[1:-1]
    kept = [first]
    total = len(first) + len(last)
    for s in middle:
        if total + len(s) > max_len:
            break
        kept.append(s)
        total += len(s)
    result = "".join(kept) + last
    if len(result) > max_len:
        cut = result[:max_len]
        i = cut.rfind("</p>")
        if i != -1:
            result = cut[:i+4]
    log(f"Статья обрезана по секциям: {len(article)} -> {len(result)} симв.")
    return result

def clean_plain(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("**", "").replace("##", "")
    s = EMOJI_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()

# ============================================================
# ПАРСИНГ СТРАНИЦЫ
# ============================================================
def clean(s):
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    for pattern in JUNK_PATTERNS:
        s = re.sub(pattern, "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()

def is_pavrus_brand(u):
    path = u.split("//", 1)[-1].split("/", 1)[-1].lower()
    return BRAND_SLUG in path

def parse_page(html_text):
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    if m:
        h1 = clean(m.group(1))
    desc = ""
    dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_text, re.S | re.I)
    if dm:
        desc = clean(dm.group(1))
    tail = re.sub(r"<script[^>]*>.*?</script>", "", html_text, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", "", tail, flags=re.S | re.I)
    tail = re.sub(r"<nav[^>]*>.*?</nav>", "", tail, flags=re.S | re.I)
    tail = re.sub(r"<header[^>]*>.*?</header>", "", tail, flags=re.S | re.I)
    tail = re.sub(r"<footer[^>]*>.*?</footer>", "", tail, flags=re.S | re.I)
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
    random.shuffle(avail)

    for attempt, page in enumerate(avail[:12]):
        html_text = pw_get_page(page)
        if not html_text or len(html_text) < 3000:
            log(f"Попытка {attempt+1}: мало данных — {page}")
            continue

        if "beget=begetok" in html_text:
            log(f"Попытка {attempt+1}: заглушка Beget — {page}")
            continue

        h1, desc, body = parse_page(html_text)
        if not h1 or (len(body) + len(desc)) < 50:
            log(f"Попытка {attempt+1}: мало текста — {page}")
            continue

        log(f"Товар PAVRUS: {h1[:70]} — {page}")
        return page, h1, desc, body

    return None, "", "", ""

# ============================================================
# ЗАГОЛОВКИ + ПОДЗАГОЛОВКИ (строгая очистка)
# ============================================================
def generate_headings_and_titles(title, desc, seeds):
    fallback = {
        "article_title": f"{title}: устройство, возможности и сценарии применения решения PAVRUS",
        "news_title": f"{title}: что интересного в этом решении PAVRUS",
        "what_is": seeds["what_is"], "purpose": seeds["purpose"],
        "features": seeds["features"], "advantages": seeds["advantages"],
        "usage": seeds["usage"], "conclusion": seeds["conclusion"],
    }

    prompt = (
        f"Ты — эксперт по профессиональному AV-оборудованию PAVRUS.\n"
        f"Придумай для статьи о товаре:\n"
        f"1. Заголовок статьи (8-14 слов)\n"
        f"2. Заголовок новости (6-10 слов)\n"
        f"3-8. Шесть подзаголовков разделов (5-10 слов каждый) на основе затравок.\n\n"
        f"ТОВАР: {title}\nОПИСАНИЕ: {desc}\n\n"
        f"ЗАТРАВКИ:\n1. {seeds['what_is']}\n2. {seeds['purpose']}\n3. {seeds['features']}\n"
        f"4. {seeds['advantages']}\n5. {seeds['usage']}\n6. {seeds['conclusion']}\n\n"
        f"КРИТИЧЕСКИ ВАЖНО: Ответь СТРОГО 8 строками текста. БЕЗ markdown, БЕЗ символов #, *, БЕЗ нумерации (1., 2.), БЕЗ вводных слов типа 'Вот заголовки'. Просто 8 строк текста."
    )

    result = gigachat_chat(prompt, GIGACHAT_MODEL or "GigaChat:latest")
    if not result:
        log("Заголовки не сгенерированы — использую запасные")
        return fallback

    lines = []
    for l in result.split("\n"):
        l = clean_plain(l).strip()
        if not l or l.startswith(("#", "*", "-", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.")):
            continue
        if "заголовок" in l.lower() and len(l) < 30:
            continue
        lines.append(l)

    if len(lines) < 8:
        log(f"ИИ вернул {len(lines)} чистых строк вместо 8 — использую запасные")
        return fallback

    out = {
        "article_title": lines[0][:120],
        "news_title": lines[1][:100],
        "what_is": lines[2][:80], "purpose": lines[3][:80],
        "features": lines[4][:80], "advantages": lines[5][:80],
        "usage": lines[6][:80], "conclusion": lines[7][:80],
    }

    log(f"Заголовок статьи: {out['article_title']}")
    log(f"Заголовок новости: {out['news_title']}")
    return out

# ============================================================
# ГЕНЕРАЦИЯ СТАТЬИ И НОВОСТИ
# ============================================================
def generate_article(title, desc, body, url, hd):
    prompt = (
        f"Напиши развёрнутую экспертную статью о профессиональном AV-оборудовании PAVRUS.\n\n"
        f"НАЗВАНИЕ ТОВАРА: {title}\n"
        f"КРАТКОЕ ОПИСАНИЕ: {desc}\n"
        f"ТЕХНИЧЕСКИЕ ХАРАКТЕРИСТИКИ: {body[:800]}\n"
        f"ССЫЛКА НА ТОВАР: {url}\n\n"
        f"ТРЕБОВАНИЯ К СТАТЬЕ:\n"
        f"1. Язык: ТОЛЬКО русский.\n"
        f"2. Длина: СТРОГО 1800-2500 символов. Длиннее 2600 — грубая ошибка!\n"
        f"3. Формат: ТОЛЬКО чистый HTML: <h2> разделы, <p> абзацы. БЕЗ markdown, БЕЗ ##, БЕЗ эмодзи, БЕЗ id-атрибутов.\n"
        f"4. НЕ пиши заголовок статьи и слово «СТАТЬЯ» — начинай сразу с первого <h2>.\n"
        f"5. СТРУКТУРА (именно эти подзаголовки):\n"
        f"    <h2>{hd['what_is']}</h2> — 2 абзаца\n"
        f"    <h2>{hd['purpose']}</h2> — 2 абзаца\n"
        f"    <h2>{hd['features']}</h2> — 2 абзаца\n"
        f"    <h2>{hd['advantages']}</h2> — 1-2 абзаца\n"
        f"    <h2>{hd['usage']}</h2> — 1 абзац\n"
        f"    <h2>{hd['conclusion']}</h2> — 1 абзац\n"
        f"6. Стиль: эксперт по AV-оборудованию, живо и конкретно, без воды.\n"
        f"7. Не выдумывай характеристики, которых нет в исходных данных.\n"
        f"8. В последнем абзаце: «По всем вопросам обращайтесь к специалистам компании PAVRUS».\n"
        f"9. 🛡️ АНТИ-НЕЙРОСЛОП: ЗАПРЕЩЕНО использовать слова: 'инновационный', 'революционный', 'в современном мире', 'стоит отметить', 'важно понимать', 'безусловно', 'играет ключевую роль', 'представляет собой', 'является'. Пиши как живой эксперт-практик, используй активный залог и конкретные факты."
    )
    article = ai_gigachat(prompt, minlen=1500)
    if not article:
        log("Объёмная статья не получилась — вторая попытка")
        prompt2 = (
            f"Статья о товаре PAVRUS «{title}». Описание: {desc}. Характеристики: {body[:500]}.\n"
            f"1500-2200 символов, чистый HTML (<h2>, <p>), без markdown и эмодзи, без заголовка в начале. Подзаголовки:\n"
            f"- {hd['what_is']}\n- {hd['purpose']}\n- {hd['features']}\n"
            f"- {hd['advantages']}\n- {hd['usage']}\n- {hd['conclusion']}\n"
            f"В конце: «По всем вопросам обращайтесь к специалистам компании PAVRUS». "
        )
        article = ai_gigachat(prompt2, minlen=1200)
    if not article:
        return None
    
    # 🛡️ ПРИНУДИТЕЛЬНАЯ ОЧИСТКА ОТ НЕЙРОСЛОПА
    article = clean_slop(article)
    article = sanitize_ai_html(article)
    article = trim_article(article, 2600)
    return article

def generate_news_from_article(article, title, hd):
    plain = clean_plain(article)
    prompt = (
        f"Сожми статью в короткую новость.\n\nСТАТЬЯ:\n{plain[:1800]}\n\nТОВАР: {title}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Длина СТРОГО 500-700 символов.\n"
        f"3. Верни ТОЛЬКО тело новости БЕЗ заголовка: 3-4 абзаца <p> и 1-2 подзаголовка <h2> внутри текста.\n"
        f"4. Формат: чистый HTML, БЕЗ markdown, БЕЗ ##, БЕЗ эмодзи, БЕЗ id-атрибутов.\n"
        f"5. Содержание: что за товар, главное применение, ключевая особенность.\n"
        f"6. В конце: «Подробнее — у специалистов PAVRUS».\n"
        f"7. 🛡️ АНТИ-НЕЙРОСЛОП: ЗАПРЕЩЕНО использовать слова: 'инновационный', 'революционный', 'в современном мире', 'стоит отметить', 'важно понимать', 'безусловно', 'играет ключевую роль', 'представляет собой', 'является'."
    )
    news = ai_gigachat(prompt, minlen=400)
    if news:
        news = clean_slop(news)
        news = sanitize_ai_html(news)
        if len(news) > 800:
            news = news[:800].rsplit("</p>", 1)[0] + "</p>"
        return news
    log("Новость не сжалась — собираю из первых предложений статьи")
    sentences = re.split(r"(?<=.)\s+", plain)
    out = []
    for s in sentences:
        s = s.strip()
        if len(s) < 20:
            continue
        out.append(s)
        if len(" ".join(out)) >= 500:
            break
    text = " ".join(out)
    if len(text) > 650:
        text = text[:650].rsplit(". ", 1)[0] + "."
    return f"<p>{text}</p><h2>Где узнать больше</h2><p>Подробнее — у специалистов PAVRUS.</p>"

# ============================================================
# СОЗДАНИЕ DOCX
# ============================================================
def html_to_lines(text):
    t = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.S | re.I)
    t = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", t, flags=re.S | re.I)
    t = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return [l.strip() for l in t.split("\n") if l.strip()]

def add_body(doc, text):
    for line in html_to_lines(text):
        if line.startswith("### "):
            doc.add_heading(line[4:], 3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], 2)
        else:
            doc.add_paragraph(line)

def create_docx(title, article_title, news_title, article, news, url, date_str, slug):
    if not DOCX_OK:
        log("python-docx не установлен — DOCX создать невозможно")
        return None
    doc = Document()
    doc.add_heading(f"PAVRUS: {title}", 0)
    doc.add_paragraph(f"Дата: {date_str}")
    doc.add_paragraph(f"Ссылка: {url}")
    doc.add_paragraph("")
    doc.add_paragraph("СТАТЬЯ")
    doc.add_paragraph(article_title)
    add_body(doc, article)
    doc.add_page_break()
    doc.add_paragraph("НОВОСТЬ")
    doc.add_paragraph(news_title)
    add_body(doc, news)
    os.makedirs("articles_output", exist_ok=True)
    path = f"articles_output/{date_str}_{slug}.docx"
    doc.save(path)
    log(f"DOCX создан: {path}")
    return path

# ============================================================
# ОТПРАВКА НА ПОЧТУ
# ============================================================
def send_email(subject, body_text, attachment_path):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or not EMAIL_TO:
        log("SMTP-настройки не заданы — пропуск отправки на почту")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        if os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(attachment_path)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)
        port = int(SMTP_PORT)
        if port == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, port, timeout=30)
        else:
            server = smtplib.SMTP(SMTP_HOST, port, timeout=30)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        log(f"Письмо отправлено на {EMAIL_TO}")
        return True
    except Exception as e:
        log(f"Ошибка отправки письма: {e}")
        return False

# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================
def main():
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
        urls = cache.get("urls", [])
        if not urls:
            log("sitemap_cache.json пуст")
            sys.exit(1)
        log(f"Локальный кэш: {len(urls)} ссылок")
    except FileNotFoundError:
        log(f"Файл {CACHE} не найден! Сначала создайте его через браузер и make_cache.py")
        sys.exit(1)

    pavrus_urls = [u for u in urls if is_pavrus_brand(u)]
    log(f"URL с брендом PAVRUS: {len(pavrus_urls)} из {len(urls)}")
    if not pavrus_urls:
        log("Нет URL с брендом PAVRUS")
        sys.exit(1)

    try:
        hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
    except Exception:
        hist = set()

    pw_ok = pw_init()
    if not pw_ok:
        log("Playwright не запустился — выход")
        sys.exit(1)

    page, title, desc, body = pick_page(pavrus_urls, hist)
    if not page:
        log("Не найдена подходящая страница PAVRUS")
        pw_close()
        sys.exit(1)

    log("Этап 3: заголовки + подзаголовки + статья (1800-2500 симв.)...")
    seeds = select_seeds()
    hd = generate_headings_and_titles(title, desc, seeds)
    article = generate_article(title, desc, body, page, hd)
    if not article:
        log("GigaChat не смог написать статью — выход")
        pw_close()
        sys.exit(1)

    log("Этап 4: генерация новости (500-700 симв.)...")
    news = generate_news_from_article(article, title, hd)
    if not news:
        log("Новость не создана — выход")
        pw_close()
        sys.exit(1)

    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)

    log("=" * 60)
    log(f"ТОВАР PAVRUS: {title}")
    log(f"ССЫЛКА: {page}")
    log(f"ЗАГОЛОВОК СТАТЬИ: {hd['article_title']}")
    log(f"ЗАГОЛОВОК НОВОСТИ: {hd['news_title']}")
    log("=" * 60)
    log(f"СТАТЬЯ: {len(article)} симв.")
    log(f"НОВОСТЬ: {len(news)} симв.")
    log("=" * 60)

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50]
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    docx_path = create_docx(title, hd["article_title"], hd["news_title"],
                            article, news, page, date_str, slug)
    if not docx_path:
        log("DOCX не создан — выход")
        pw_close()
        sys.exit(1)

    subject = f"PAVRUS: {title} — статья и новость {date_str}"
    body = (f"Добрый день!\n\n"
            f"Сгенерирована статья о товаре PAVRUS.\n\n"
            f"Товар: {title}\n"
            f"Ссылка: {page}\n\n"
            f"Заголовок статьи: {hd['article_title']}\n"
            f"Заголовок новости: {hd['news_title']}\n\n"
            f"Длина статьи: {len(article)} симв.\n"
            f"Длина новости: {len(news)} симв.\n\n"
            f"Во вложении — DOCX со статьёй и новостью для ручной публикации.\n\n"
            f"С уважением,\nPAVRUS Articles Agent")

    send_email(subject, body, docx_path)

    pw_close()
    log("=" * 50)
    log("FINISH: статья + новость отправлены на почту!")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        log(traceback.format_exc())
        raise
