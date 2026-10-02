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
# КОНФИГУРАЦИЯ (ВСЕ ПРОБЕЛЫ ВНУТРИ КАВЫЧЕК УДАЛЕНЫ)
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

# 🛡️ АНТИ-НЕЙРОСЛОП
ANTI_SLOP_REPLACEMENTS = {
    "представляет собой": "", "является": "", "стоит отметить": "",
    "важно понимать": "", "безусловно": "", "в современном мире": "",
    "играет ключевую роль": "", "инновационный": "современный",
    "революционный": "новый", "подводя итог": "", "в заключение": "",
    "таким образом": "", "не стоит забывать": "", "следует отметить": ""
}

def clean_slop(text):
    for slop, replacement in ANTI_SLOP_REPLACEMENTS.items():
        text = re.sub(r"\b" + slop + r"\b", replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()

HEADING_SEEDS = {
    "what_is": ["Что представляет собой устройство", "Принцип работы устройства", "Техническая справка", "Общее описание", "Анатомия решения", "Знакомство с устройством", "Главное о продукте", "Для чего создано устройство"],
    "purpose": ["Сценарии применения", "Место в AV-инсталляции", "Роль и задачи устройства", "Области интеграции", "Целевые объекты", "Для кого создано это решение", "Ищем точку приложения", "Практическое применение"],
    "features": ["Матрица технических характеристик", "Функциональные возможности", "Варианты подключения и интерфейсы", "Полный разбор возможностей", "Логика работы решения", "Полезный функционал", "Ключевые возможности", "Технические особенности"],
    "advantages": ["Конструктивные преимущества", "Отличительные инженерные решения", "Почему эта модель выигрывает", "Схемотехника и надежность", "Конкурентные отличия", "Важнейшие детали устройства", "Преимущественные фишки", "Уникальные технологии"],
    "usage": ["Рекомендации по использованию", "Требования к монтажу", "Особенности эксплуатации", "Практические советы", "Лайфхаки по применению", "Быстрый старт", "Настраиваем устройство", "Способы инсталляции"],
    "conclusion": ["Технические выводы", "Экспертное заключение", "Реальное применение", "Устройство стоит своих денег", "Честный вердикт", "Переход на новый уровень", "Следующий шаг клиента", "Эффективность применения"],
}

def select_seeds():
    return {k: random.choice(v) for k, v in HEADING_SEEDS.items()}

def log(msg):
    print(msg, flush=True)

log("pavrus-articles-agent v18 (Playwright, локальный кэш, АНТИ-НЕЙРОСЛОП)")

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
            headers={"Authorization": f"Basic {credentials}", "RqUID": str(uuid.uuid4()), "Content-Type": "application/x-www-form-urlencoded"},
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
                      "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
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
# ЗАГОЛОВКИ + ПОДЗАГОЛОВКИ
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
        if not l or l.startswith(("#
