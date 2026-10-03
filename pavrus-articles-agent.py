# -*- coding: utf-8 -*-
"""
pavrus-articles-agent v36
Исправлено: чтение env-переменных по ДВУМ именам (ID/ID1, USER/LOGIN, PASS/PASSWORD, EMAIL_TO/MAIL_TO);
GIGACHAT_SCOPE и GIGACHAT_MODEL из секретов; pollinations с повтором; диагностика ключей на старте.
"""
import os, json, datetime, time, re, html, smtplib, urllib3
from urllib.parse import urljoin
from email.message import EmailMessage
urllib3.disable_warnings()

SITE = "https://pavrus.ru"
SITEMAP_CACHE = "sitemap_cache.json"
SENT_HISTORY = "sent_history.json"

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# v36: читаем ОБА варианта имён секретов
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

ANTI_SLOP = ("Пиши неровно и конкретно: разная длина предложений, детали вместо оценок; "
             "ЗАПРЕЩЕНЫ клише «погружает», «не оставит равнодушным», «захватывает с первых страниц», "
             "«судьбы переплетаются», «заставляет задуматься», «не только…, но и…», вилки «от… до…», "
             "итоговые резюме «таким образом»; не более одного тире на абзац и одного восклицания на текст.")

def log(msg):
    print(msg, flush=True)

log("Версия ℹ️ pavrus-articles-agent v36 (env-имена с фолбэками; GIGACHAT_SCOPE/MODEL из секретов; pollinations с повтором; диагностика ключей)")
log(f"🔑 Ключи: gigachat={'ДА' if GIGACHAT_CLIENT_ID else 'НЕТ'}, cerebras={'ДА' if CEREBRAS_KEY else 'НЕТ'}, "
    f"mistral={'ДА' if MISTRAL_KEY else 'НЕТ'}, groq={'ДА' if GROQ_KEY else 'НЕТ'}, "
    f"openrouter={'ДА' if OR_KEY else 'НЕТ'}, smtp={'ДА' if SMTP_HOST else 'НЕТ'}, получателей={len(MAIL_TO)}")

# ============================================================
# СЕТЬ И КАРТА САЙТА (curl-cffi → playwright → requests)
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
    sitemap_url = f"{SITE}/sitemap-iblock-91.xml"
    r = http_get(sitemap_url)
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

def fetch_page_text(url, limit=6000):
    r = http_get(url)
    if r is None or not r.ok:
        return ""
    if len(r.content) < 500:
        log(f"⚠️ Страница вернула заглушку ({len(r.content)} байт) — пропускаю")
        return ""
    t = re.sub(r"(?is)<(script|style|noscript|svg|head).*?>.*?</\1>", " ", r.text)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < 200:
        log(f"⚠️ Текст страницы слишком короткий ({len(t)} симв.) — пропускаю")
        return ""
    log(f"📄 Текст страницы: {len(t)} симв.")
    return t[:limit]

# ============================================================
# ИИ-ЦЕПОЧКА (v36: scope/model из секретов, pollinations с повтором)
# ============================================================

def _extract(r):
    try: return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError): return None

def _err_snippet(r):
    e = r.get("error") or {}
    code = e.get("code") or e.get("type") or "?"
    msg = str(e.get("message") or e)
    return f"{code}: {msg[:100]}"

_GIGACHAT_TOKEN = None
_GIGACHAT_TOKEN_EXPIRY = 0

def get_gigachat_token():
    global _GIGACHAT_TOKEN, _GIGACHAT_TOKEN_EXPIRY
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        log("   ⚠️ gigachat: ID/SECRET не заданы")
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
        log(f"ℹ️ GigaChat OAuth: статус {r.status_code} (scope={GIGACHAT_SCOPE})")
        if r.status_code != 200:
            log(f"⚠️ GigaChat OAuth тело: {r.text[:200]}")
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
    if not token:
        log("   ⚠️ gigachat: токен не получен")
        return None
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
        if "choices" not in j or not j["choices"]:
            log(f"   ⚠️ gigachat: пустой ответ: {str(j)[:200]}")
            return None
        text = j["choices"][0]["message"]["content"].strip()
        if not text:
            log("   ⚠️ gigachat: пустой текст")
            return None
        log(f"   ✅ gigachat ({GIGACHAT_MODEL}): {len(text)} симв.")
        return text
    except Exception as e:
        log(f"   ⚠️ gigachat error: {e}")
        return None

def ai_cerebras(prompt):
    if not CEREBRAS_KEY:
        log("   ⚠️ cerebras: ключ не задан")
        return None
    try:
        import requests
        r = requests.post("https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_KEY}"},
            json={"model": "llama-3.3-70b", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ cerebras: {_err_snippet(r)}")
            return None
        text = _extract(r)
        if not text:
            log("   ⚠️ cerebras: пустой текст")
            return None
        log(f"   ✅ cerebras: {len(text)} симв.")
        return text
    except Exception as e:
        log(f"   ⚠️ cerebras error: {e}")
        return None

def ai_mistral(prompt):
    if not MISTRAL_KEY:
        log("   ⚠️ mistral: ключ не задан")
        return None
    try:
        import requests
        r = requests.post("https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_KEY}"},
            json={"model": "mistral-small-latest", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ mistral: {_err_snippet(r)}")
            return None
        text = _extract(r)
        if not text:
            log("   ⚠️ mistral: пустой текст")
            return None
        log(f"   ✅ mistral: {len(text)} симв.")
        return text
    except Exception as e:
        log(f"   ⚠️ mistral error: {e}")
        return None

def ai_groq(prompt, key, model):
    if not key:
        return None
    try:
        import requests
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ groq {model}: {_err_snippet(r)}")
            return None
        text = _extract(r)
        if not text:
            log(f"   ⚠️ groq {model}: пустой текст")
            return None
        log(f"   ✅ groq {model}: {len(text)} симв.")
        return text
    except Exception as e:
        log(f"   ⚠️ groq {model} error: {e}")
        return None

def ai_openrouter_auto(prompt, key, max_tokens):
    if not key:
        return None
    try:
        import requests
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com"},
            json={"model": "auto", "temperature": 0.8, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ openrouter (max={max_tokens}): {_err_snippet(r)}")
            return None
        text = _extract(r)
        if not text:
            log(f"   ⚠️ openrouter (max={max_tokens}): пустой текст")
            return None
        log(f"   ✅ openrouter (max={max_tokens}): {len(text)} симв.")
        return text
    except Exception as e:
        log(f"   ⚠️ openrouter error: {e}")
        return None

def ai_pollinations_text(prompt):
    """v36: две попытки, контроль статуса."""
    for attempt in range(2):
        try:
            import requests
            r = requests.post("https://text.pollinations.ai/openai",
                json={"model": "openai", "temperature": 0.8,
                      "messages": [{"role": "user", "content": prompt + RU}]}, timeout=90)
            if r.status_code != 200:
                log(f"   ⚠️ pollinations-text: статус {r.status_code} (попытка {attempt+1})")
                time.sleep(3)
                continue
            text = _extract(r.json())
            if text:
                log(f"   ✅ pollinations-text: {len(text)} симв.")
                return text
            log(f"   ⚠️ pollinations-text: пустой текст (попытка {attempt+1})")
        except Exception as e:
            log(f"   ⚠️ pollinations-text error: {str(e)[:80]}")
        time.sleep(3)
    return None

def ai_text(prompt, minlen=1500, rescue_min=1200):
    best_res = ""

    def take(res, label):
        nonlocal best_res
        if not res:
            return None
        if len(res) >= minlen:
            log(f"✅ Успех: {label}, {len(res)} симв.")
            return res
        log(f"   ⚠️ {label}: текст короче нужного ({len(res)}/{minlen}) — запомнен кандидатом")
        if len(res) > len(best_res):
            best_res = res
        return None

    log("🔄 Попытка: gigachat...")
    r = take(ai_gigachat(prompt), "gigachat")
    if r: return r
    log("🔄 Попытка: cerebras (llama-3.3-70b)...")
    r = take(ai_cerebras(prompt), "cerebras")
    if r: return r
    log("🔄 Попытка: mistral (mistral-small)...")
    r = take(ai_mistral(prompt), "mistral")
    if r: return r
    for i, key in enumerate((GROQ_KEY, GROQ_KEY2)):
        if not key: continue
        for model in GROQ_MODELS:
            log(f"🔄 Попытка: groq ({model}, ключ {i+1})...")
            r = take(ai_groq(prompt, key, model), f"groq ({model})")
            if r: return r
    for i, key in enumerate((OR_KEY, OR_KEY2)):
        if not key: continue
        for mt in (4000, 2000):
            log(f"🔄 Попытка: openrouter auto (max={mt}, ключ {i+1})...")
            r = take(ai_openrouter_auto(prompt, key, mt), f"openrouter (max={mt})")
            if r: return r
    log("🔄 Попытка: pollinations-text (без ключа)...")
    r = take(ai_pollinations_text(prompt), "pollinations-text")
    if r: return r
    if best_res and len(best_res) >= rescue_min:
        log(f"ℹ️ Беру лучший кандидат ({len(best_res)} симв.)")
        return best_res
    log("❌ Все провайдеры не дали текст достаточной длины")
    return None

def extend_text(txt, target):
    if not txt or len(txt) >= target:
        return txt
    ext = ai_gigachat(
        f"Расширь текст до {target}-{target+400} символов, сохранив стиль, смысл и структуру. "
        f"Добавь детали и конкретику. Без ссылок и Markdown.\n\nТЕКСТ:\n{txt}")
    if ext and len(ext) >= target:
        log(f"✅ Расширено: {len(ext)} симв.")
        return ext
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
    log(f"📏 Длина статьи: {len(txt)} симв. (коридор 2000-2500)")
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
    "Перепиши текст ниже на русском, СОХРАНИВ смысл, структуру, факты и объём (±10%), "
    "но убери маркеры машинного письма: {flags}. Запрещено: оценочные клише, "
    "«не только…, но и…», вилки «от… до…», шаблон «X — это Y», вводные слова в начале абзацев, "
    "итоговые резюме. Пиши неровно: чередуй короткие и длинные предложения, добавь конкретику "
    "вместо оценок. Верни ТОЛЬКО очищенный текст.")

def anti_slop(txt, label="статья", threshold=3.0):
    score, flags = slop_check(txt)
    log(f"🧼 slop-score {label}: {score:.1f}/1000 знаков, флагов: {len(flags)}")
    for f in flags[:8]:
        log(f"   • {f['name']}: «{f['quote']}»")
    if score <= threshold or not flags:
        return txt
    fl = "; ".join(sorted({f['name'] for f in flags}))
    fixed = ai_gigachat(SLOP_FIX_PROMPT.format(flags=fl))
    if not fixed:
        return txt
    score2, flags2 = slop_check(fixed)
    log(f"🧼 после fix-прохода: {score2:.1f}/1000 (было {score:.1f}), флагов: {len(flags2)}")
    return fixed if score2 < score else txt

# ============================================================
# СТАТЬЯ
# ============================================================

def clean_txt(t):
    return t.replace("**", "").replace("##", "").replace("#", "").strip()

def build_article(page_url, page_text):
    prompt = (f"Напиши статью для авторской рассылки по материалу страницы сайта Павла Гнесюка. "
              f"Содержание страницы (фрагмент): {page_text[:4000]} "
              f"Требования: 1. ТОЛЬКО русский язык. "
              f"2. Заголовок до 110 символов, живой, БЕЗ слов-меток «Заголовок/Статья». "
              f"3. Объём СТРОГО 2000-2500 символов, 5-7 абзацев: крючок-вступление, суть материала, "
              f"детали и атмосфера, ключевой момент, финал с вопросом читателю. "
              f"4. В ТЕЛЕ статьи НЕ должно быть URL, доменов и слов «ссылка», «перейти». "
              f"5. НЕ используй Markdown. {ANTI_SLOP}")
    txt = ai_text(prompt, minlen=1500, rescue_min=1200)
    if not txt:
        log("⚠️ Статья не создана — пропускаю отправку")
        return None
    txt = clean_txt(txt)
    txt = anti_slop(txt)
    txt = enforce_length(txt)
    return txt

# ============================================================
# ПОЧТА (v36: имена SMTP_USER/SMTP_PASS/EMAIL_TO тоже понимаются)
# ============================================================

def send_email(subject, body):
    if not SMTP_HOST or not SMTP_LOGIN or not MAIL_TO:
        log(f"⚠️ Почта не настроена: host={'ДА' if SMTP_HOST else 'НЕТ'}, login={'ДА' if SMTP_LOGIN else 'НЕТ'}, получателей={len(MAIL_TO)}")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject[:150]
        msg["From"] = MAIL_FROM
        msg["To"] = ", ".join(MAIL_TO)
        msg.set_content(body)
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
# ГЛАВНАЯ ЛОГИКА
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
        page_text = fetch_page_text(page)
        if not page_text:
            log("⚠️ Страница не парсится, пробую следующую...")
            continue

        article = build_article(page, page_text)
        if not article:
            continue

        headline = article.split("\n")[0].strip()
        body = (article +
                f"\n\n---\nПолный материал на сайте: {page}\nПавел Гнесюк — музыка и книги.")

        ok = send_email(headline, body)
        if ok:
            sent[page] = str(datetime.date.today())
            save_history(sent)
            log("=" * 50)
            log(f"✅ FINISH: статья {len(article)} симв. → почта: ДА")
            log("=" * 50)
            return

    log("=" * 50)
    log("❌ FINISH: все кандидаты не парсятся или ИИ не сгенерировал текст")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
