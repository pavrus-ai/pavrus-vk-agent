# -*- coding: utf-8 -*-
import os, re, json, random, datetime, smtplib, ssl, time, html as html_lib, urllib3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
urllib3.disable_warnings()

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except Exception:
    HAS_CFFI = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
SITE = "https://pavrus.ru"
SITEMAP_URL = SITE + "/sitemap-iblock-91.xml"
CACHE_FILE = "addresses_cache.json"
FAILED_FILE = "failed_urls.json"
USED_FILE = "used_urls.json"
HISTORY_FILE = "article_history.json"

ARTICLE_LEN = (2000, 2500)
NEWS_LEN = (700, 1000)
MIN_SOURCE = 200          # минимум символов источника, иначе карточка "пустая"
CANDIDATES_N = 15         # было 5 — стало 15
MAX_PER_SECTION = 3       # не больше 3 URL из одного раздела каталога

GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID1", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET1", "").strip()
GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465").strip() or 465)
SMTP_LOGIN = os.environ.get("SMTP_LOGIN", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip()
RECIPIENTS = os.environ.get("RECIPIENTS", "").strip()

def log(msg):
    print(msg, flush=True)

log("Версия ℹ️ pavrus-articles-agent v42 (свежий sitemap + случайные кандидаты + blacklist + specs-fallback)")

# ============================================================
# СЕТЬ И ПАРСИНГ
# ============================================================
def fetch(url, timeout=60):
    if HAS_CFFI:
        try:
            r = cffi_requests.get(url, impersonate="chrome120", timeout=timeout, verify=False)
            log(f"✅ curl-cffi: {url} → статус {r.status_code}, {len(r.content)} байт")
            return r.text if r.status_code == 200 else None
        except Exception as e:
            log(f"⚠️ curl-cffi ошибка: {str(e)[:100]}")
    try:
        r = requests.get(url, timeout=timeout, verify=False,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        log(f"✅ requests: {url} → статус {r.status_code}, {len(r.content)} байт")
        return r.text if r.status_code == 200 else None
    except Exception as e:
        log(f"⚠️ requests ошибка: {str(e)[:100]}")
        return None

def clean(s):
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def parse_sitemap(xml):
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", xml or "", re.S)

def extract_page(html):
    """Возвращает (title, text, specs). specs — строки таблиц характеристик."""
    title, text_parts, specs = "", [], []
    if HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "")
        for sel in ["div[itemprop='description']", "div.description", "div.text", "article", "main"]:
            node = soup.select_one(sel)
            if not node:
                continue
            for p in node.find_all(["p", "li", "h2", "h3"]):
                t = p.get_text(" ", strip=True)
                if len(t) > 40:
                    text_parts.append(t)
            if text_parts:
                break
        for table in soup.find_all("table")[:3]:
            for row in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    specs.append(f"{cells[0]}: {cells[1]}")
    else:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        title = clean(m.group(1)) if m else ""
        for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, re.S | re.I):
            t = clean(m.group(1))
            if len(t) > 40:
                text_parts.append(t)
        for m in re.finditer(r"<tr[^>]*>\s*<t[hd][^>]*>(.*?)</t[hd]>\s*<t[hd][^>]*>(.*?)</t[hd]", html, re.S | re.I):
            specs.append(f"{clean(m.group(1))}: {clean(m.group(2))}")
    return title, " ".join(text_parts).strip(), specs

# ============================================================
# КЭШ АДРЕСОВ И ЧЁРНЫЕ СПИСКИ
# ============================================================
def load_json(path, default):
    try:
        if os.path.exists(path):
            return json.load(open(path, encoding="utf-8"))
    except Exception:
        pass
    return default

def save_json(path, data):
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def get_addresses():
    """СВЕЖИЙ sitemap — основной источник. Кэш — только аварийный."""
    xml = fetch(SITEMAP_URL)
    urls = parse_sitemap(xml)
    if len(urls) > 100:
        save_json(CACHE_FILE, {"date": datetime.date.today().isoformat(), "urls": urls})
        log(f"✅ Пул из СВЕЖЕГО sitemap: {len(urls)} адресов")
        return urls
    cache = load_json(CACHE_FILE, {})
    urls = cache.get("urls", [])
    age = "неизвестен"
    if cache.get("date"):
        age = (datetime.date.today() - datetime.date.fromisoformat(cache["date"])).days
    log(f"⚠️ Sitemap не распознан, беру кэш: {len(urls)} адресов, возраст {age} дн.")
    return urls

def pick_candidates(addresses):
    """Настоящий случайный выбор: весь пул минус used/failed, ротация разделов."""
    failed = set(load_json(FAILED_FILE, []))
    used = set(load_json(USED_FILE, []))
    pool = [u for u in addresses if u not in failed and u not in used]
    if len(pool) < CANDIDATES_N:
        pool = [u for u in addresses if u not in failed]   # второй круг: reused разрешён
    random.shuffle(pool)
    picked, per_sec = [], {}
    for u in pool:
        sec = "/".join(u.split("/")[:6])
        per_sec[sec] = per_sec.get(sec, 0) + 1
        if per_sec[sec] <= MAX_PER_SECTION:
            picked.append(u)
        if len(picked) >= CANDIDATES_N:
            break
    log(f"🎲 Кандидаты ({len(picked)}):")
    for i, u in enumerate(picked, 1):
        log(f"   {i}. {u}")
    return picked

# ============================================================
# ГЕНЕРАЦИЯ ТЕКСТА (GigaChat → Groq)
# ============================================================
_G_TOKEN, _G_EXP = None, 0

def gigachat_token():
    global _G_TOKEN, _G_EXP
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        return None
    if _G_TOKEN and time.time() < _G_EXP:
        return _G_TOKEN
    try:
        cred = __import__("base64").b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                          headers={"Authorization": f"Basic {cred}", "RqUID": str(__import__("uuid").uuid4()),
                                   "Content-Type": "application/x-www-form-urlencoded"},
                          data={"scope": "GIGACHAT_API_PERS"}, timeout=30, verify=False)
        if r.status_code == 200 and "access_token" in r.json():
            _G_TOKEN = r.json()["access_token"]
            _G_EXP = time.time() + 1700
            return _G_TOKEN
    except Exception as e:
        log(f"⚠️ GigaChat auth: {e}")
    return None

def ai_generate(prompt, minlen, maxlen):
    def ok(t):
        return t if t and minlen <= len(t) <= maxlen else None
    token = gigachat_token()
    if token:
        try:
            r = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                              headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                              json={"model": "GigaChat:latest", "temperature": 0.8, "max_tokens": 4000,
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=120, verify=False)
            if r.status_code == 200:
                res = ok(r.json()["choices"][0]["message"]["content"].strip())
                if res:
                    log(f"✅ gigachat: {len(res)} симв.")
                    return res
        except Exception as e:
            log(f"⚠️ GigaChat: {e}")
    if GROQ_KEY:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {GROQ_KEY}"},
                              json={"model": "llama-3.1-8b-instant", "temperature": 0.8,
                                    "messages": [{"role": "user", "content": prompt}]}, timeout=90).json()
            if "error" not in r:
                res = ok(r["choices"][0]["message"]["content"].strip())
                if res:
                    log(f"✅ groq: {len(res)} симв.")
                    return res
        except Exception as e:
            log(f"⚠️ Groq: {e}")
    return None

def build_text(title, source, kind):
    lo, hi = (ARTICLE_LEN if kind == "article" else NEWS_LEN)
    role = "полноценную SEO-статью" if kind == "article" else "короткую новость-анонс"
    prompt = (
        f"Ты — редактор блога интернет-магазина Паврус (pavrus.ru). Напиши {role} на русском: «{title}».\n"
        f"Источник фактов (перескажи своими словами, НЕ копируй кусками):\n{source[:6000]}\n"
        f"Требования: 1) Объём СТРОГО {lo}–{hi} символов. "
        f"2) {'Структура: лид, 2–3 подзаголовка, абзацы, вывод.' if kind == 'article' else 'Структура: лид, 1–2 абзаца фактов, финальная фраза.'} "
        f"3) ЗАПРЕТ на штампы: «в современном мире», «стоит отметить», «данное изделие», «невероятный», «уникальный в своём роде». "
        f"4) Только факты и польза: характеристики, применение, кому подходит. "
        f"5) Без ссылок, цен, e-mail. 6) Без служебных пометок в тексте."
    )
    return ai_generate(prompt, int(lo * 0.9), int(hi * 1.1))

# ============================================================
# ОТПРАВКА ПИСЬМА
# ============================================================
def send_email(subject, body_text, source_url):
    recipients = [r.strip() for r in RECIPIENTS.split(",") if r.strip()]
    if not (SMTP_HOST and SMTP_LOGIN and SMTP_PASSWORD and recipients):
        log("⚠️ SMTP не настроен — письмо не отправлено")
        return False
    html_body = "<br>".join(body_text.split("\n")) + f"<br><br><i>Источник: {source_url}</i>"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or SMTP_LOGIN
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=60) as s:
            s.login(SMTP_LOGIN, SMTP_PASSWORD)
            s.sendmail(msg["From"], recipients, msg.as_string())
        log(f"✅ Письмо отправлено: {len(recipients)} получ.")
        return True
    except Exception as e:
        log(f"⚠️ SMTP ошибка: {e}")
        return False

# ============================================================
# ГЛАВНЫЙ ЦИКЛ
# ============================================================
def main():
    addresses = get_addresses()
    if not addresses:
        log("❌ Нет адресов — выход")
        raise SystemExit(1)

    candidates = pick_candidates(addresses)
    failed_list = load_json(FAILED_FILE, [])
    used_list = load_json(USED_FILE, [])
    history = load_json(HISTORY_FILE, [])

    sent = False
    for url in candidates:
        page = fetch(url)
        if not page:
            continue
        title, text, specs = extract_page(page)

        source = text
        if len(source) < MIN_SOURCE:
            # СПАСЕНИЕ: собираем источник из таблицы характеристик
            specs_text = "; ".join(specs)
            if len(specs_text) >= MIN_SOURCE:
                source = f"{title}. Характеристики: {specs_text}"
                log(f"⚠️ Описания нет — собрал источник из характеристик ({len(source)} симв.)")
            else:
                log(f"⚠️ {url}: пусто (нет ни описания, ни характеристик) → в blacklist")
                if url not in failed_list:
                    failed_list.append(url)
                continue   # не тратим попытку — берём следующего кандидата

        kind = "article" if len(source) >= 600 else "news"
        log(f"📝 Тип текста: {kind} (источник {len(source)} симв.)")
        body = build_text(title or url.rstrip("/").split("/")[-1], source, kind)
        if not body:
            log("⚠️ ИИ не смог уложиться в длину — пробую следующего кандидата")
            if url not in failed_list:
                failed_list.append(url)
            continue

        subject = f"Статья для pavrus.ru: {title or url}"[:120]
        if send_email(subject, body, url):
            sent = True
            if url not in used_list:
                used_list.append(url)
            history.append({"date": datetime.date.today().isoformat(), "url": url, "kind": kind, "title": title})
            break

    save_json(FAILED_FILE, failed_list[-500:])
    save_json(USED_FILE, used_list[-2000:])
    save_json(HISTORY_FILE, history[-500:])
    log("=" * 50)
    log(f"✅ FINISH: статья {'ОТПРАВЛЕНА' if sent else 'НЕ отправлена'}")
    if not sent:
        raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
