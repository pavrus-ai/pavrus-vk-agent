# -*- coding: utf-8 -*-
"""
pavrus-articles-agent v41
v40 + анти-нейрослоп на НОВОСТИ (prompt + fix-проход),
ANTI_SLOP в промпте расширения, переизмерение длины новости,
сохранение подзаголовков ## в новости (баг v40: replace("#") убивал их).
Длины: Статья 2000-2500, Новость 700-1000 — фиксируются после анти-слопа.
"""
import os, json, datetime, time, re, html, smtplib, io, urllib3
from urllib.parse import urljoin
from email.message import EmailMessage
urllib3.disable_warnings()

SITE = "https://pavrus.ru"
SITEMAP_CACHE = "sitemap_cache.json"
SENT_HISTORY = "sent_history.json"

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

GIGACHAT_CLIENT_ID = (os.environ.get("GIGACHAT_CLIENT_ID1") or os.environ.get("GIGACHAT_CLIENT_ID") or "").strip()
GIGACHAT_CLIENT_SECRET = (os.environ.get("GIGACHAT_CLIENT_SECRET1") or os.environ.get("GIGACHAT_CLIENT_SECRET") or "").strip()
GIGACHAT_SCOPE = (os.environ.get("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS").strip()
GIGACHAT_MODEL = (os.environ.get("GIGACHAT_MODEL") or "GigaChat:latest").strip()
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "").strip()
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "").strip()
GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
GROQ_KEY2 = os.environ.get("GROQ_KEY2", "").strip()
OR_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
OR_KEY2 = os.environ.get("OPENROUTER_KEY2", "").strip()

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465").strip() or 465)
SMTP_LOGIN = (os.environ.get("SMTP_LOGIN") or os.environ.get("SMTP_USER") or "").strip()
SMTP_PASSWORD = (os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS") or "").strip()
MAIL_FROM = (os.environ.get("MAIL_FROM") or SMTP_LOGIN).strip()
MAIL_TO = [x.strip() for x in (os.environ.get("MAIL_TO") or os.environ.get("EMAIL_TO") or "").split(",") if x.strip()]

RU = "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."
GROQ_MODELS = ["meta-llama/llama-4-scout-17b-16e-instruct",
               "meta-llama/llama-4-maverick-17b-128e-instruct",
               "openai/gpt-oss-120b",
               "llama-3.1-8b-instant"]

BRAND_RULE = ("Имя бренда и компании пиши ТОЛЬКО латиницей: PAVRUS. "
              "ЗАПРЕЩЕНО писать «Паврус», «Паврюс», «ПАВРУС» и любые кириллические транслитерации бренда.")

ANTI_SLOP = ("Пиши неровно и конкретно: разная длина предложений, детали вместо оценок; "
             "ЗАПРЕЩЕНЫ клише «погружает», «не оставит равнодушным», «захватывает с первых страниц», "
             "«судьбы переплетаются», «заставляет задуматься», «не только…, но и…», вилки «от… до…», "
             "итоговые резюме «таким образом»; не более одного тире на абзац и одного восклицания на текст.")

def log(msg):
    print(msg, flush=True)

log("Версия ℹ️ pavrus-articles-agent v41 (анти-слоп на Статье И Новости; ## сохраняются; длины: Статья 2000-2500, Новость 700-1000)")
log(f"🔑 Ключи: gigachat={'ДА' if GIGACHAT_CLIENT_ID else 'НЕТ'}, smtp={'ДА' if SMTP_HOST else 'НЕТ'}, получателей={len(MAIL_TO)}")

# ============================================================
# БРЕНД
# ============================================================

def fix_brand(txt):
    fixed = re.sub(r'Паврюс|Паврус|ПАВРЮС|ПАВРУС|паврюс|паврус', 'PAVRUS', txt)
    if fixed != txt:
        log("🏷️ fix_brand: кириллическая транслитерация бренда заменена на PAVRUS")
    return fixed

# ============================================================
# ФИЛЬТР СТОРОННИХ БРЕНДОВ
# ============================================================

THIRD_PARTY_BRANDS = [
    r'\bCypress\b', r'\bGefen\b', r'\bChiayo\b', r'\bClearOne\b', r'\bShure\b',
    r'\bSennheiser\b', r'\bBosch\b', r'\bBeyerdynamic\b', r'\bAudio-Technica\b',
    r'\bAKG\b', r'\bJBL\b', r'\bYamaha\b', r'\bSony\b', r'\bPanasonic\b'
]

def check_pavrus_product(text):
    if re.search(r'\bPAVRUS\b', text, re.IGNORECASE):
        return True
    for pattern in THIRD_PARTY_BRANDS:
        if re.search(pattern, text, re.IGNORECASE):
            return False
    return False

# ============================================================
# СЕТЬ И КАРТА САЙТА
# ============================================================

def http_get_curl_cffi(url, timeout=30):
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, timeout=timeout, impersonate="chrome",
                              headers={"Accept-Language": "ru,en;q=0.8"})
        log(f"✅ curl-cffi: {url} → статус {r.status_code}, {len(r.content)} байт")
        return r
    except ImportError:
        return None
    except Exception as e:
        log(f"⚠️ curl-cffi ошибка: {str(e)[:80]}")
        return None

def http_get_playwright(url, timeout=30):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000)
            content = page.content()
            browser.close()
            log(f"✅ playwright: {url} → {len(content)} байт")
            class FakeResponse:
                def __init__(self, text, status):
                    self.text = text
                    self.content = text.encode()
                    self.status_code = status
                    self.ok = status == 200
            return FakeResponse(content, 200)
    except ImportError:
        return None
    except Exception as e:
        log(f"⚠️ playwright ошибка: {str(e)[:80]}")
        return None

def http_get_requests(url, timeout=30):
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": BROWSER_UA,
                                  "Accept-Language": "ru,en;q=0.8"})
        log(f"ℹ️ requests: {url} → статус {r.status_code}, {len(r.content)} байт")
        return r
    except Exception as e:
        log(f"⚠️ requests ошибка: {str(e)[:80]}")
        return None

def http_get(url, timeout=30, tries=3):
    for i in range(tries):
        r = http_get_curl_cffi(url, timeout)
        if r and r.ok and len(r.content) > 500:
            return r
        r = http_get_playwright(url, timeout)
        if r and r.ok and len(r.content) > 500:
            return r
        r = http_get_requests(url, timeout)
        if r and r.ok and len(r.content) > 500:
            return r
        log(f"⚠️ Попытка {i+1}/{tries}: заглушка или ошибка, жду 5 сек...")
        time.sleep(5)
    return None

def fetch_sitemap():
    r = http_get(f"{SITE}/sitemap-iblock-91.xml")
    if r and r.ok and ("<urlset" in r.text or "<sitemapindex" in r.text):
        urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
        urls = [u for u in urls if "/catalog/" in u]
        if urls:
            return sorted(set(urls))
    r = http_get(SITE + "/")
    if r and r.ok:
        urls = [urljoin(SITE, u) for u in re.findall(r'href="([^"]+)"', r.text)]
        urls = [u for u in urls if u.startswith(SITE) and "/catalog/" in u]
        return sorted(set(urls))
    return []

def save_sitemap_cache(urls):
    try:
        json.dump({"updated": datetime.date.today().toordinal(),
                   "date": str(datetime.date.today()),
                   "urls": urls},
                  open(SITEMAP_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"💾 Кэш карты сайта обновлён: {len(urls)} адресов")
    except Exception as e:
        log(f"⚠️ save_sitemap_cache: {e}")

def get_site_map():
    urls = fetch_sitemap()
    if urls:
        save_sitemap_cache(urls)
        log(f"✅ Карта сайта получена напрямую: {len(urls)} адресов")
        return urls
    try:
        cache = json.load(open(SITEMAP_CACHE, encoding="utf-8"))
        if cache.get("urls"):
            age = datetime.date.today().toordinal() - cache.get("updated", 0)
            log(f"⚠️ Сайт из GitHub недоступен — беру кэш: {len(cache['urls'])} адресов, возраст {age} дн.")
            return cache["urls"]
    except Exception:
        pass
    log("❌ Сайт недоступен и кэш пуст — пропускаю запуск")
    return []

# ============================================================
# ИСТОРИЯ ОТПРАВОК
# ============================================================

def load_history():
    try:
        d = json.load(open(SENT_HISTORY, encoding="utf-8"))
        return d.get("sent", {})
    except Exception:
        return {}

def save_history(sent):
    try:
        json.dump({"sent": sent}, open(SENT_HISTORY, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        log(f"💾 История отправок: {len(sent)} записей")
    except Exception as e:
        log(f"⚠️ save_history: {e}")

def pick_pages(urls, sent, count=5):
    fresh = [u for u in urls if u not in sent and "/catalog/" in u]
    if not fresh:
        log("ℹ️ Все подходящие страницы уже отправлены ранее")
        return []
    day = datetime.date.today().toordinal()
    sorted_urls = sorted(fresh)
    start = day % len(sorted_urls)
    candidates = sorted_urls[start:start+count]
    if len(candidates) < count:
        candidates += sorted_urls[:count-len(candidates)]
    log(f"🎯 Кандидаты ({len(candidates)}):")
    for i, u in enumerate(candidates, 1):
        log(f"   {i}. {u}")
    return candidates

def parse_page(url):
    r = http_get(url)
    if r is None or not r.ok or len(r.content) < 500:
        return None
    title = None
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", r.text)
    if m:
        title = re.sub(r"(?s)<[^>]+>", "", m.group(1))
        title = html.unescape(title).strip()
        title = re.sub(r"\s+", " ", title)
    t = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer|header).*?>.*?</\1>", " ", r.text)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < 200:
        log(f"⚠️ Текст страницы слишком короткий ({len(t)} симв.)")
        return None
    if not check_pavrus_product(t):
        log(f"⚠️ Страница не про продукцию PAVRUS — пропускаю")
        return None
    log(f"📄 Страница: заголовок = «{(title or '(нет)')[:60]}», текст {len(t)} симв. (продукция PAVRUS)")
    return {"title": (title or "")[:200], "text": t[:6000], "url": url}

# ============================================================
# ИИ-ЦЕПОЧКА
# ============================================================

def _extract(r):
    try: return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError): return None

_GIGACHAT_TOKEN = None
_GIGACHAT_TOKEN_EXPIRY = 0

def get_gigachat_token():
    global _GIGACHAT_TOKEN, _GIGACHAT_TOKEN_EXPIRY
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        return None
    if _GIGACHAT_TOKEN and time.time() < _GIGACHAT_TOKEN_EXPIRY:
        return _GIGACHAT_TOKEN
    try:
        import base64, uuid, requests
        credentials = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={"Authorization": f"Basic {credentials}",
                     "RqUID": str(uuid.uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"scope": GIGACHAT_SCOPE}, timeout=30, verify=False)
        if r.status_code != 200:
            log(f"⚠️ GigaChat OAuth: {r.text[:200]}")
            return None
        j = r.json()
        if "access_token" in j:
            _GIGACHAT_TOKEN = j["access_token"]
            _GIGACHAT_TOKEN_EXPIRY = time.time() + 1700
            log("✅ GigaChat: токен получен (действует 30 мин)")
            return _GIGACHAT_TOKEN
    except Exception as e:
        log(f"⚠️ GigaChat auth error: {e}")
    return None

def ai_gigachat(prompt):
    token = get_gigachat_token()
    if not token: return None
    try:
        import requests
        r = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": GIGACHAT_MODEL, "temperature": 0.9, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt + RU}]},
            timeout=120, verify=False)
        if r.status_code != 200:
            log(f"   ⚠️ gigachat: статус {r.status_code}: {r.text[:200]}")
            return None
        j = r.json()
        text = (j.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if text:
            log(f"   ✅ gigachat ({GIGACHAT_MODEL}): {len(text)} симв.")
            return text
    except Exception as e:
        log(f"   ⚠️ gigachat error: {e}")
    return None

def ai_cerebras(prompt):
    if not CEREBRAS_KEY: return None
    try:
        import requests
        r = requests.post("https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_KEY}"},
            json={"model": "llama-3.3-70b", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_mistral(prompt):
    if not MISTRAL_KEY: return None
    try:
        import requests
        r = requests.post("https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_KEY}"},
            json={"model": "mistral-small-latest", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_groq(prompt, key, model):
    if not key: return None
    try:
        import requests
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_openrouter_auto(prompt, key, max_tokens):
    if not key: return None
    try:
        import requests
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com"},
            json={"model": "auto", "temperature": 0.8, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_pollinations_text(prompt):
    for attempt in range(2):
        try:
            import requests
            r = requests.post("https://text.pollinations.ai/openai",
                json={"model": "openai", "temperature": 0.8,
                      "messages": [{"role": "user", "content": prompt + RU}]}, timeout=90)
            if r.status_code != 200:
                time.sleep(3); continue
            text = _extract(r.json())
            if text: return text
        except Exception: pass
        time.sleep(3)
    return None

def ai_text(prompt, minlen=1500, rescue_min=1200):
    best_res = ""
    def take(res, label):
        nonlocal best_res
        if not res: return None
        if len(res) >= minlen:
            log(f"✅ Успех: {label}, {len(res)} симв.")
            return res
        if len(res) > len(best_res):
            best_res = res
        return None
    log("🔄 Попытка: gigachat...")
    r = take(ai_gigachat(prompt), "gigachat")
    if r: return r
    log("🔄 Попытка: cerebras...")
    r = take(ai_cerebras(prompt), "cerebras")
    if r: return r
    log("🔄 Попытка: mistral...")
    r = take(ai_mistral(prompt), "mistral")
    if r: return r
    for i, key in enumerate((GROQ_KEY, GROQ_KEY2)):
        if not key: continue
        for model in GROQ_MODELS:
            r = take(ai_groq(prompt, key, model), f"groq ({model})")
            if r: return r
    for i, key in enumerate((OR_KEY, OR_KEY2)):
        if not key: continue
        for mt in (4000, 2000):
            r = take(ai_openrouter_auto(prompt, key, mt), f"openrouter (max={mt})")
            if r: return r
    log("🔄 Попытка: pollinations-text...")
    r = take(ai_pollinations_text(prompt), "pollinations-text")
    if r: return r
    if best_res and len(best_res) >= rescue_min:
        return best_res
    log("❌ Все провайдеры не дали текст")
    return None

def clean_md(txt):
    """v41: убирает ** и __, но СОХРАНЯЕТ ## подзаголовки."""
    return txt.replace("**", "").replace("__", "").strip()

def extend_text(txt, target):
    if not txt or len(txt) >= target: return txt
    ext = ai_gigachat(
        f"Расширь текст до {target}-{target+400} символов, сохранив стиль, смысл и подзаголовки (##). "
        f"Без ссылок; Markdown только ##. {BRAND_RULE} {ANTI_SLOP}\n\nТЕКСТ:\n{txt}")  # v41: +ANTI_SLOP
    if ext and len(ext) >= target: return ext
    return txt

def trim_text(t, limit):
    if len(t) <= limit: return t
    c = t[:limit]
    i = max(c.rfind("."), c.rfind("!"), c.rfind("?"), c.rfind("\n"))
    return (c[:i+1] if i > limit//2 else c).rstrip()

def enforce_length(txt, lo=2000, hi=2500, target=2200):
    if len(txt) < lo:
        txt = extend_text(txt, target)
    if len(txt) > hi:
        txt = trim_text(txt, hi)
    log(f"📏 Длина: {len(txt)} симв.")
    return txt

# ============================================================
# АНТИ-НЕЙРОСЛОП
# ============================================================

SLOP_PATTERNS = [
    (r"погружа\w+\s+в\s+(атмосфер\w*|мир\w*)", "клише «погружает в атмосферу/мир»", 2),
    (r"не\s+остав\w+\s+равнодушн\w*", "клише «не оставит равнодушным»", 2),
    (r"захват\w+\s+с\s+перв\w+\s+(страниц|секунд)", "клише «захватывает с первых страниц»", 2),
    (r"заставля\w+\s+задум\w*", "клише «заставляет задуматься»", 2),
    (r"судьб\w+\s+переплет\w*", "клише «судьбы переплетаются»", 2),
    (r"мир[о,е]?\s+(полн\w+|полный)\s+\w+\s+и\s+\w+", "клише «мир, полный X и Y»", 2),
    (r"настоящ\w+\s+подарок\s+для", "клише «настоящий подарок для»", 2),
    (r"борьба\s+добра\s+и\s+зла|борьб\w+\s+света\s+и\s+тьмы", "штамп «борьба добра и зла»", 2),
    (r"не\s+только\s+[^,]{3,60},\s+но\s+и", "конструкция «не только…, но и…»", 1),
    (r"от\s+[а-яёa-z-]{4,20}\s+до\s+[а-яёa-z-]{4,20}", "абстрактная вилка «от… до…»", 1),
    (r"[а-яё,)\s]+ — это\s+", "шаблон «X — это Y»", 1),
    (r"^(однако|впрочем|между\s+тем|безусловно|действительно|более\s+того|тем\s+не\s+менее)\b",
     "абзац с вводного слова", 1),
    (r"(таким\s+образом|в\s+конечном\s+итоге|в\s+заключени[еи])\b", "итоговое резюме", 1),
]

def slop_check(txt):
    flags = []
    low = txt.lower()
    n = max(len(txt), 1)
    for pat, name, weight in SLOP_PATTERNS:
        for m in re.finditer(pat, low):
            flags.append({"name": name, "weight": weight,
                          "quote": txt[m.start():m.start()+60].strip()})
    sents = [s.strip() for s in re.split(r'[.!?]+\s', txt) if len(s.strip()) > 10]
    if len(sents) >= 5:
        lens = [len(s) for s in sents]
        mean = sum(lens)/len(lens)
        var = (sum((l-mean)**2 for l in lens)/len(lens)) ** 0.5
        if mean > 0 and var/mean < 0.35:
            flags.append({"name": "метроном: одинаковая длина предложений", "weight": 2,
                          "quote": f"σ/μ={var/mean:.2f}"})
    if txt.count(" — ") > n/700:
        flags.append({"name": "плотность тире выше нормы", "weight": 1, "quote": "—"})
    score = sum(f["weight"] for f in flags) * 1000.0 / n
    return score, flags

SLOP_FIX_PROMPT = (
    "Перепиши текст ниже на русском, СОХРАНИВ смысл, структуру, подзаголовки (##) и объём (±10%), "
    "но убери маркеры машинного письма: {flags}. Запрещено: оценочные клише, "
    "«не только…, но и…», вилки «от… до…», шаблон «X — это Y», вводные слова в начале абзацев, "
    "итоговые резюме. Верни ТОЛЬКО очищенный текст.")

def anti_slop(txt, label="текст", threshold=3.0):
    score, flags = slop_check(txt)
    log(f"🧼 slop-score {label}: {score:.1f}/1000 знаков, флагов: {len(flags)}")
    for f in flags[:8]:
        log(f"   • {f['name']}: «{f['quote']}»")
    if score <= threshold or not flags:
        return txt
    fl = "; ".join(sorted({f['name'] for f in flags}))
    fixed = ai_gigachat(SLOP_FIX_PROMPT.format(flags=fl))
    if not fixed: return txt
    score2, flags2 = slop_check(fixed)
    log(f"🧼 после fix-прохода: {score2:.1f}/1000 (было {score:.1f})")
    return fixed if score2 < score else txt

# ============================================================
# СТАТЬЯ (2000-2500, с подзаголовками, только про PAVRUS)
# ============================================================

def build_article(page_data):
    page_title = page_data.get("title") or "(заголовок не извлечён)"
    page_url = page_data.get("url", "")
    page_text = page_data.get("text", "")[:4000]
    prompt = (f"Напиши статью для авторской рассылки компании PAVRUS. "
              f"ВАЖНО: пиши ИСКЛЮЧИТЕЛЬНО про продукцию и решения PAVRUS. "
              f"ЗАПРЕЩЕНО писать про сторонние бренды (Cypress, Gefen, Chiayo, ClearOne, Shure и т.д.) — "
              f"игнорируй их, пиши только про PAVRUS. "
              f"Заголовок страницы (ориентир): «{page_title}»\n"
              f"Адрес страницы: {page_url}\n"
              f"Содержание страницы (фрагмент): {page_text}\n"
              f"Требования: 1. ТОЛЬКО русский язык. {BRAND_RULE} "
              f"2. Заголовок до 110 символов, основан на продукции PAVRUS со страницы, "
              f"БЕЗ слов-меток «Заголовок/Статья». "
              f"3. СТРУКТУРА С ПОДЗАГОЛОВКАМИ (Markdown ## для подзаголовков): "
              f"   - Вступление (без подзаголовка): крючок про конкретный продукт PAVRUS "
              f"   - ## Назначение и применение "
              f"   - ## Ключевые характеристики "
              f"   - ## Типовые задачи "
              f"   - ## Преимущества решения PAVRUS "
              f"4. Объём СТРОГО 2000-2500 символов (включая подзаголовки). "
              f"5. ОБЯЗАТЕЛЬНО используй название продукции PAVRUS со страницы «{page_title}». "
              f"6. ЗАПРЕЩЕНО: общие фразы типа «широкий ассортимент», «каталог оборудования», "
              f"«вся линейка», «наши решения». "
              f"7. В ТЕЛЕ статьи НЕ должно быть URL, доменов и слов «ссылка», «перейти». "
              f"8. НЕ используй Markdown кроме ## для подзаголовков. {ANTI_SLOP}")
    txt = ai_text(prompt, minlen=1500, rescue_min=1200)
    if not txt:
        log("⚠️ Статья не создана — пропускаю отправку")
        return None
    txt = clean_md(txt)                      # v41: ** убираем, ## сохраняем
    txt = anti_slop(txt, label="статья")
    txt = enforce_length(txt, lo=2000, hi=2500, target=2200)
    txt = fix_brand(txt)
    return txt

# ============================================================
# НОВОСТЬ (700-1000, сокращённая статья, с подзаголовками) — v41: +анти-слоп
# ============================================================

def build_news(article):
    prompt = (f"Сократи следующую статью до 700-1000 символов, СОХРАНИВ структуру с подзаголовками (##). "
              f"Убери детали, оставь самое важное: назначение, ключевые характеристики, преимущества. "
              f"Используй Markdown ## для подзаголовков, другой Markdown запрещён. "
              f"Верни ТОЛЬКО сокращённый текст (Новость). {ANTI_SLOP}\n\n"   # v41: +ANTI_SLOP
              f"СТАТЬЯ:\n{article}")
    news = ai_text(prompt, minlen=600, rescue_min=500)
    if not news:
        log("⚠️ Новость не создана — использую обрезку статьи")
        news = trim_text(article, 1000)
    news = clean_md(news)                    # v41: ** убираем, ## СОХРАНЯЕМ (баг v40)
    news = anti_slop(news, label="новость")  # v41: анти-слоп на новости
    news = fix_brand(news)
    # v41: переизмерение длины после каждого шага (баг v40: старое значение)
    if len(news) < 700:
        log(f"⚠️ Новость коротковата ({len(news)} симв.) — расширяю")
        news = extend_text(news, 700)
    if len(news) > 1000:
        news = trim_text(news, 1000)
    log(f"📰 Новость: {len(news)} симв.")
    return news

# ============================================================
# DOCX = Статья + Новость (оба с подзаголовками)
# ============================================================

def build_docx(headline, article, news):
    try:
        from docx import Document
    except ImportError:
        log("⚠️ python-docx не установлен — вложения не будет")
        return None
    try:
        doc = Document()
        doc.add_heading(headline, level=1)
        for line in article.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("## "):
                doc.add_heading(line[3:], level=2)
            else:
                doc.add_paragraph(line)
        doc.add_page_break()
        doc.add_heading(f"Новость: {headline}", level=1)
        for line in news.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("## "):
                doc.add_heading(line[3:], level=2)
            else:
                doc.add_paragraph(line)
        buf = io.BytesIO()
        doc.save(buf)
        data = buf.getvalue()
        log(f"📎 DOCX собран (Статья + Новость): {len(data)} байт")
        return data
    except Exception as e:
        log(f"⚠️ build_docx ошибка: {str(e)[:120]}")
        return None

# ============================================================
# ПОЧТА
# ============================================================

def send_email(subject, body, docx_bytes=None, filename="PAVRUS_article.docx"):
    if not SMTP_HOST or not SMTP_LOGIN or not MAIL_TO:
        log(f"⚠️ Почта не настроена")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject[:150]
        msg["From"] = MAIL_FROM
        msg["To"] = ", ".join(MAIL_TO)
        msg.set_content(body)
        if docx_bytes:
            msg.add_attachment(
                docx_bytes,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename=filename)
            log(f"📎 Вложение добавлено: {filename}")
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60)
            server.starttls()
        server.login(SMTP_LOGIN, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        log(f"✅ Письмо отправлено: {len(MAIL_TO)} получателям, тема: {subject[:80]}")
        return True
    except Exception as e:
        log(f"❌ Ошибка отправки письма: {str(e)[:150]}")
        return False

# ============================================================
# ГЛАВНАЯ ЛОГИКА v41
# ============================================================

def main():
    urls = get_site_map()
    if not urls:
        return

    sent = load_history()
    candidates = pick_pages(urls, sent, count=5)
    if not candidates:
        log("ℹ️ Новых страниц нет — письмо сегодня не отправляем")
        return

    for i, page in enumerate(candidates, 1):
        log(f"\n🔄 Попытка {i}/{len(candidates)}: {page}")
        page_data = parse_page(page)
        if not page_data or not page_data.get("text"):
            log("⚠️ Страница не парсится или не про PAVRUS, пробую следующую...")
            continue

        article = build_article(page_data)
        if not article:
            continue

        headline = fix_brand(article.split("\n")[0].strip() or page_data["title"])
        news = build_news(article)

        body_lines = ["Здравствуйте!\n"]
        body_lines.append(f"Полная статья «{headline}» и новость — во вложении (файл DOCX).")
        body_lines.append("")
        body_lines.append("--")
        body_lines.append("PAVRUS")
        body = "\n".join(body_lines)

        day = datetime.date.today().toordinal()
        docx_bytes = build_docx(headline, article, news)
        filename = f"PAVRUS_article_{day}.docx"

        ok = send_email(headline, body, docx_bytes, filename)
        if ok:
            sent[page] = str(datetime.date.today())
            save_history(sent)
            log("=" * 50)
            log(f"✅ FINISH: Статья {len(article)} симв. + Новость {len(news)} симв. → DOCX → почта: ДА")
            log("=" * 50)
            return

    log("=" * 50)
    log("❌ FINISH: все кандидаты не парсятся, не про PAVRUS или ИИ не сгенерировал текст")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
