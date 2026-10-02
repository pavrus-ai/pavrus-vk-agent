# -*- coding: utf-8 -*-
"""
pavrus-articles-agent v33
Берёт материал со сайта pavrus.ru (sitemap → кэш любого возраста),
пишет статью 2000-2500 символов с анти-слопом и отправляет её по почте.
История отправок и кэш карты сайта — JSON-файлы в репозитории.
"""
import os, json, datetime, time, re, html, smtplib, urllib3, requests
from urllib.parse import urljoin
from email.message import EmailMessage
urllib3.disable_warnings()

SITE = "https://pavrus.ru"
SITEMAP_CACHE = "sitemap_cache.json"
SENT_HISTORY = "sent_history.json"

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# AI-ключи
GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID1", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET1", "").strip()
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "").strip()
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "").strip()
GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
GROQ_KEY2 = os.environ.get("GROQ_KEY2", "").strip()
OR_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
OR_KEY2 = os.environ.get("OPENROUTER_KEY2", "").strip()

# Почта
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465").strip() or 465)
SMTP_LOGIN = os.environ.get("SMTP_LOGIN", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "").strip() or SMTP_LOGIN
MAIL_TO = [x.strip() for x in os.environ.get("MAIL_TO", "").split(",") if x.strip()]

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

log("Версия ℹ️ pavrus-articles-agent v33 (кэш карты любого возраста; browser UA + retry; история в JSON; статьи 2000-2500; анти-слоп; ссылка только в подвале письма)")

# ============================================================
# СЕТЬ И КАРТА САЙТА
# ============================================================

def http_get(url, timeout=30, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": BROWSER_UA,
                                      "Accept-Language": "ru,en;q=0.8"})
            log(f"ℹ️ GET {url} → статус {r.status_code}, {len(r.content)} байт")
            return r
        except Exception as e:
            log(f"⚠️ GET {url} попытка {i+1}: {str(e)[:80]}")
            time.sleep(5 * (i + 1))
    return None

def fetch_sitemap():
    for sm in ("/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml", "/wp-sitemap.xml"):
        r = http_get(SITE + sm)
        if r is not None and r.ok and ("<urlset" in r.text or "<sitemapindex" in r.text):
            urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
            if urls:
                return sorted(set(urls))
    r = http_get(SITE + "/")
    if r is not None and r.ok:
        urls = [urljoin(SITE, u) for u in re.findall(r'href="([^"]+)"', r.text)]
        return sorted({u for u in urls if u.startswith(SITE)})
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
    """v33: сайт → кэш ЛЮБОГО возраста → пропуск. Не пропускаем запуск, если кэш жив."""
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
# ИСТОРИЯ ОТПРАВОК (JSON — не рвётся, как текстовик)
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

SKIP_URL_PARTS = (".mp3", ".jpg", ".jpeg", ".png", ".xml", "/feed", "/wp-",
                  "/tag/", "/tags/", "/category/", "/cgi-bin", ".ico", ".css", ".js")

def pick_page(urls, sent):
    fresh = [u for u in urls
             if u not in sent
             and not u.rstrip("/").endswith(SITE.rstrip("/").split("//")[-1])
             and not any(p in u.lower() for p in SKIP_URL_PARTS)]
    if not fresh:
        log("ℹ️ Все подходящие страницы уже отправлены ранее")
        return None
    day = datetime.date.today().toordinal()
    pick = sorted(fresh)[day % len(fresh)]
    log(f" Выбрана страница дня: {pick} (новых кандидатов: {len(fresh)})")
    return pick

def fetch_page_text(url, limit=6000):
    r = http_get(url)
    if r is None or not r.ok:
        return ""
    t = re.sub(r"(?is)<(script|style|noscript|svg|head).*?>.*?</\1>", " ", r.text)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]

# ============================================================
# ИИ-ЦЕПОЧКА ТЕКСТА
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
        credentials = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode() if False else \
            __import__("base64").b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={"Authorization": f"Basic {credentials}",
                     "RqUID": str(__import__("uuid").uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"scope": "GIGACHAT_API_PERS"}, timeout=30, verify=False)
        log(f"ℹ️ GigaChat OAuth: статус {r.status_code}")
        if r.status_code != 200:
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
        return None
    try:
        r = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": "GigaChat:latest", "temperature": 0.9, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt + RU}]},
            timeout=120, verify=False)
        if r.status_code != 200:
            log(f"⚠️ GigaChat chat: статус {r.status_code}: {r.text[:200]}")
            return None
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log(f"⚠️ GigaChat error: {e}")
        return None

def ai_cerebras(prompt):
    if not CEREBRAS_KEY: return None
    try:
        r = requests.post("https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_KEY}"},
            json={"model": "llama-3.3-70b", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        return None if "error" in r else _extract(r)
    except Exception as e:
        log(f"   ⚠️ cerebras: {str(e)[:80]}")
        return None

def ai_mistral(prompt):
    if not MISTRAL_KEY: return None
    try:
        r = requests.post("https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_KEY}"},
            json={"model": "mistral-small-latest", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        return None if "error" in r else _extract(r)
    except Exception as e:
        log(f"   ⚠️ mistral: {str(e)[:80]}")
        return None

def ai_groq(prompt, key, model):
    if not key: return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        return None if "error" in r else _extract(r)
    except Exception as e:
        log(f"   ⚠️ groq {model}: {str(e)[:80]}")
        return None

def ai_openrouter_auto(prompt, key, max_tokens):
    if not key: return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com"},
            json={"model": "auto", "temperature": 0.8, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt + RU}]}, timeout=60).json()
        return None if "error" in r else _extract(r)
    except Exception as e:
        log(f"   ⚠️ openrouter auto: {str(e)[:80]}")
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
        if len(res) > len(best_res):
            best_res = res
        return None

    log("🔄 Попытка: gigachat (GigaChat:latest)...")
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
    if best_res and len(best_res) >= rescue_min:
        log(f"ℹ️ Беру лучший кандидат ({len(best_res)} симв.)")
        return best_res
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
# ПОЧТА
# ============================================================

def send_email(subject, body):
    if not SMTP_HOST or not SMTP_LOGIN or not MAIL_TO:
        log("⚠️ SMTP_HOST/SMTP_LOGIN/MAIL_TO не заданы — письмо не отправлено")
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
    page = pick_page(urls, sent)
    if not page:
        log("ℹ️ Новых страниц нет — письмо сегодня не отправляем")
        return

    page_text = fetch_page_text(page)
    if not page_text:
        log("⚠️ Не удалось получить текст страницы — пропускаю запуск")
        return
    log(f"📄 Текст страницы: {len(page_text)} симв.")

    article = build_article(page, page_text)
    if not article:
        return

    headline = article.split("\n")[0].strip()
    # v33: ссылка на сайт — ТОЛЬКО в подвале письма (тело статьи чистое)
    body = (article +
            f"\n\n---\nПолный материал на сайте: {page}\nПавел Гнесюк — музыка и книги.")

    ok = send_email(headline, body)
    if ok:
        sent[page] = str(datetime.date.today())
        save_history(sent)

    log("=" * 50)
    log(f"✅ FINISH: статья {len(article)} симв. → почта: {'ДА' if ok else 'НЕТ'}")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
