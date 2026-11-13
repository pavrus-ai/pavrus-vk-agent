# -*- coding: utf-8 -*-
import os, re, json, glob, random, datetime, smtplib, ssl, time, html as html_lib, urllib3, base64, uuid
from urllib.parse import quote
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
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
try:
    from docx import Document
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False

SITE = "https://pavrus.ru"
SITEMAP_URL = SITE + "/sitemap-iblock-91.xml"
CACHE_FILE = "addresses_cache.json"
SEED_FILE = "addresses_seed.json"
FAILED_FILE = "failed_urls.json"
USED_FILE = "used_urls.json"
HISTORY_FILE = "article_history.json"
FEEDS = [SITE + "/upload/yandex/market.yml", SITE + "/yandex-market.xml",
         SITE + "/upload/iblock/yandex/yandex.xml", SITE + "/market.xml"]

BRAND = "PAVRUS"
ARTICLE_LEN = (2000, 2500)
NEWS_LEN = (700, 1000)
MIN_SOURCE = 200
CANDIDATES_N = 15
MAX_PER_SECTION = 3

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
IMPERSONATES = ["chrome124", "chrome120", "safari17_0", "edge101"]

GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID1", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET1", "").strip()
GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
COOKIES = os.environ.get("PAVRUS_COOKIES", "").strip()
FALLBACK_NEWS = os.environ.get("FALLBACK_NEWS", "1").strip() != "0"
SMTP_HOST = (os.environ.get("SMTP_HOST") or os.environ.get("SMTP_SERVER") or os.environ.get("MAIL_HOST") or "").strip()
SMTP_PORT = int((os.environ.get("SMTP_PORT") or "465").strip() or 465)
SMTP_LOGIN = (os.environ.get("SMTP_LOGIN") or os.environ.get("SMTP_USER") or os.environ.get("MAIL_USER") or "").strip()
SMTP_PASSWORD = (os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS") or os.environ.get("MAIL_PASSWORD") or "").strip()
SMTP_FROM = (os.environ.get("SMTP_FROM") or os.environ.get("MAIL_FROM") or "").strip()
RECIPIENTS = (os.environ.get("RECIPIENTS") or os.environ.get("MAIL_TO") or os.environ.get("EMAIL_TO") or os.environ.get("RECIPIENT") or "").strip()

def log(msg):
    print(msg, flush=True)

log("Версия ℹ️ pavrus-articles-agent v49 (вложение .docx + только бренд PAVRUS)")
log(f"🔑 Ключи: gigachat={'ДА' if GIGACHAT_CLIENT_ID else 'НЕТ'}, "
    f"smtp={'ДА' if (SMTP_HOST and SMTP_LOGIN and SMTP_PASSWORD) else 'НЕТ'}, "
    f"получателей={len([r for r in RECIPIENTS.split(',') if r.strip()])}, "
    f"docx={'ДА' if HAS_DOCX else 'НЕТ'}")

def is_killbot(html):
    return bool(html) and "killbot" in html.lower()

def is_pavrus_brand(url):
    """Только товары бренда PAVRUS: метка бренда в пути URL после домена."""
    path = url[len(SITE):] if url.startswith(SITE) else url
    return "pavrus" in path.lower()

# ============================================================
# HEADLESS-БРАУЗЕР (запасной уровень)
# ============================================================
class Browser:
    def __init__(self):
        self.ok = False
        self._pw = self._br = self._ctx = None

    def start(self):
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._br = self._pw.chromium.launch(headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            self._ctx = self._br.new_context(user_agent=UA, locale="ru-RU",
                                             viewport={"width": 1366, "height": 900})
            if COOKIES:
                ck = []
                for part in COOKIES.split(";"):
                    if "=" in part:
                        k, v = part.strip().split("=", 1)
                        ck.append({"name": k, "value": v, "domain": ".pavrus.ru", "path": "/"})
                self._ctx.add_cookies(ck)
            self.ok = True
            log("✅ Headless-браузер запущен")
        except Exception as e:
            log(f"⚠️ Playwright недоступен: {str(e)[:120]}")
        return self.ok

    def get(self, url, tries=2):
        if not self.ok:
            return None
        page = self._ctx.new_page()
        html = None
        try:
            for i in range(tries):
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                for _ in range(6):
                    html = page.content()
                    if not is_killbot(html):
                        break
                    page.wait_for_timeout(2500)
                if not is_killbot(html):
                    return html
                page.wait_for_timeout(3000)
            return html
        except Exception as e:
            log(f"⚠️ browser ошибка: {str(e)[:100]}")
            return html
        finally:
            try: page.close()
            except Exception: pass

    def close(self):
        try:
            if self._br: self._br.close()
            if self._pw: self._pw.stop()
        except Exception:
            pass

# ============================================================
# FETCH
# ============================================================
def fetch_text(url, timeout=60, use_cookies=True):
    hdr = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
           "Referer": SITE + "/"}
    if COOKIES and use_cookies:
        hdr["Cookie"] = COOKIES
    if HAS_CFFI:
        for imp in IMPERSONATES:
            try:
                r = cffi_requests.get(url, impersonate=imp, timeout=timeout, verify=False, headers=hdr)
                log(f"✅ curl-cffi[{imp}]: {url[:80]} → статус {r.status_code}, {len(r.content)} байт")
                if r.status_code == 200 and len(r.content) > 500:
                    return r.text
            except Exception as e:
                log(f"⚠️ curl-cffi[{imp}] ошибка: {str(e)[:80]}")
            time.sleep(1)
    try:
        r = requests.get(url, timeout=timeout, verify=False, headers=dict(hdr, **{"User-Agent": UA}))
        log(f"✅ requests: {url[:80]} → статус {r.status_code}, {len(r.content)} байт")
        if r.status_code == 200:
            return r.text
    except Exception as e:
        log(f"⚠️ requests ошибка: {str(e)[:80]}")
    return None

def fetch_smart(browser, url):
    if COOKIES:
        p = fetch_text(url)
        if p and not is_killbot(p):
            return p
    if browser.ok:
        p = browser.get(url)
        if p and not is_killbot(p):
            return p
    p = fetch_text(url, use_cookies=False)
    if p and not is_killbot(p):
        return p
    return None

# ============================================================
# АРХИВЫ
# ============================================================
def wayback_cdx_pool(limit=3000):
    try:
        q = (f"https://web.archive.org/cdx/search/cdx?url={quote(SITE.replace('https://', ''))}/catalog/*"
             f"&output=json&collapse=urlkey&filter=statuscode:200&limit={limit}&fl=original")
        r = requests.get(q, timeout=180)
        rows = r.json()[1:]
        urls = []
        for row in rows:
            if not row or not row[0]:
                continue
            u = html_lib.unescape(row[0])
            if not u.startswith("http"):
                u = "https://" + u
            u = u.replace("http://", "https://", 1)
            if u.startswith(SITE):
                urls.append(u)
        log(f"🕰 Wayback CDX: сохранённых страниц каталога: {len(urls)}")
        return urls
    except Exception as e:
        log(f"⚠️ CDX ошибка: {str(e)[:100]}")
        return []

def wayback_latest(url):
    try:
        q = (f"https://web.archive.org/cdx/search/cdx?url={quote(url)}"
             f"&output=json&filter=statuscode:200&fl=timestamp&limit=-1")
        r = requests.get(q, timeout=60)
        rows = r.json()[1:]
        if not rows:
            return None
        ts = rows[-1][0]
        snap = f"https://web.archive.org/web/{ts}id_/{url}"
        body = fetch_text(snap, use_cookies=False, timeout=90)
        if body and len(body) > 2000 and not is_killbot(body):
            log(f"🕰 Wayback слепок {ts}: {url[:70]}")
            return body
    except Exception as e:
        log(f"⚠️ wayback_latest: {str(e)[:80]}")
    return None

def fetch_archive_today(url):
    target = f"https://archive.ph/newest/{url}"
    body, final = None, target
    if HAS_CFFI:
        try:
            r = cffi_requests.get(target, impersonate="chrome124", timeout=60, verify=False,
                                  headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"})
            body, final = r.text, r.url
            log(f"✅ archive.ph: статус {r.status_code}, {len(r.content)} байт, финал: {final[:70]}")
        except Exception as e:
            log(f"⚠️ archive.ph: {str(e)[:80]}")
    if body and "/newest/" in final:
        log("⚠️ archive.ph: слепка страницы нет — пропускаю")
        return None
    if body and len(body) > 2000 and "captcha" not in body.lower():
        log("🕰 archive.today: слепок получен")
        return body
    return None

def ddg_source(query):
    snippets = []
    q = f'"{query}" характеристики OR описание OR купить'
    engines = [
        ("ddg-html", "https://html.duckduckgo.com/html/", {"q": q}, ".result__snippet"),
        ("ddg-lite", "https://lite.duckduckgo.com/lite/", {"q": q}, ".result-snippet, td.result-snippet"),
        ("bing", f"https://www.bing.com/search?q={quote(q)}&setlang=ru", None, "li.b_algo p"),
    ]
    for name, url, data, sel in engines:
        try:
            if data:
                r = (cffi_requests.post(url, data=data, impersonate="chrome124", timeout=30) if HAS_CFFI
                     else requests.post(url, data=data, headers={"User-Agent": UA}, timeout=30))
            else:
                r = (cffi_requests.get(url, impersonate="chrome124", timeout=30) if HAS_CFFI
                     else requests.get(url, headers={"User-Agent": UA}, timeout=30))
            if r.status_code != 200 or not HAS_BS4:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for s in soup.select(sel)[:8]:
                t = s.get_text(" ", strip=True)
                if len(t) > 30:
                    snippets.append(t)
            log(f"🔎 Сниппеты [{name}] для «{query}»: {len(snippets)}")
            if snippets:
                return snippets
        except Exception as e:
            log(f"⚠️ Сниппеты [{name}]: {str(e)[:60]}")
    return snippets

# ============================================================
# АДРЕСА И СПИСКИ
# ============================================================
def parse_sitemap(xml):
    if not xml:
        return []
    return [html_lib.unescape(u).strip() for u in re.findall(r"<loc[^>]*>\s*(.*?)\s*</loc>", xml, re.S)]

def extract_urls(body):
    if not body:
        return []
    if "<loc" in body.lower():
        locs = parse_sitemap(body)
        pages = [u for u in locs if not u.lower().endswith(".xml")]
        children = [u for u in locs if u.lower().endswith(".xml")]
        if len(pages) < 100 and children:
            for child in children[:12]:
                pages += [u for u in parse_sitemap(fetch_text(child)) if not u.lower().endswith(".xml")]
        return pages
    if "<url>" in body.lower():
        return re.findall(r"<url>\s*(.*?)\s*</url>", body, re.S)
    return []

def load_json(path, default):
    try:
        if os.path.exists(path):
            return json.load(open(path, encoding="utf-8"))
    except Exception:
        pass
    return default

def save_json(path, data):
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def find_legacy_addresses():
    skip = {CACHE_FILE, SEED_FILE, FAILED_FILE, USED_FILE, HISTORY_FILE}
    best = []
    for path in sorted(glob.glob("*.json")):
        if path in skip:
            continue
        data = load_json(path, None)
        cand = []
        if isinstance(data, list):
            cand = [x for x in data if isinstance(x, str) and x.startswith("http")]
        elif isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    cand += [x for x in v if isinstance(x, str) and x.startswith("http")]
        cand = [x for x in cand if SITE in x]
        if len(cand) > len(best):
            best = cand
    if best:
        log(f"🔎 Старый кэш найден: {len(best)} адресов")
    return best

def get_addresses(browser):
    pool = wayback_cdx_pool()
    if len(pool) >= 50:
        save_json(CACHE_FILE, {"date": datetime.date.today().isoformat(), "urls": pool})
        return pool
    if browser.ok:
        urls = [u for u in extract_urls(browser.get(SITEMAP_URL)) if u.startswith(SITE)]
        if len(urls) >= 100:
            save_json(CACHE_FILE, {"date": datetime.date.today().isoformat(), "urls": urls})
            log(f"✅ Адреса через браузер: {len(urls)}")
            return urls
    if COOKIES:
        urls = [u for u in extract_urls(fetch_text(SITEMAP_URL)) if u.startswith(SITE)]
        if len(urls) >= 100:
            save_json(CACHE_FILE, {"date": datetime.date.today().isoformat(), "urls": urls})
            log(f"✅ Адреса с куками: {len(urls)}")
            return urls
    for f in FEEDS:
        urls = [u for u in extract_urls(fetch_text(f)) if u.startswith(SITE)]
        if len(urls) >= 100:
            save_json(CACHE_FILE, {"date": datetime.date.today().isoformat(), "urls": urls})
            log(f"✅ Адреса из фида: {len(urls)}")
            return urls
    seed = load_json(SEED_FILE, [])
    if isinstance(seed, dict):
        seed = seed.get("urls", [])
    if seed:
        return seed
    legacy = find_legacy_addresses()
    if legacy:
        save_json(CACHE_FILE, {"date": datetime.date.today().isoformat(), "urls": legacy})
        return legacy
    return load_json(CACHE_FILE, {}).get("urls", [])

def pick_candidates(addresses):
    failed = set(load_json(FAILED_FILE, []))
    used = set(load_json(USED_FILE, []))
    pool = [u for u in addresses if u not in failed and u not in used]
    if len(pool) < CANDIDATES_N:
        pool = [u for u in addresses if u not in failed]
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
# ПАРСИНГ
# ============================================================
def clean(s):
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def extract_page(html):
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
    return title, " ".join(text_parts).strip(), specs

def slug_to_name(url):
    parts = [p for p in url.split("/") if p]
    name = parts[-1].replace("-", " ").replace("_", " ").strip() if parts else url
    cat = parts[-2].replace("-", " ").replace("_", " ").strip() if len(parts) >= 2 else ""
    return name, cat

# ============================================================
# ГЕНЕРАЦИЯ ТЕКСТА
# ============================================================
_G_TOKEN, _G_EXP = None, 0

def gigachat_token():
    global _G_TOKEN, _G_EXP
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        return None
    if _G_TOKEN and time.time() < _G_EXP:
        return _G_TOKEN
    try:
        cred = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                          headers={"Authorization": f"Basic {cred}", "RqUID": str(uuid.uuid4()),
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

def build_text(title, source, kind, nospecs=False):
    lo, hi = (ARTICLE_LEN if kind == "article" else NEWS_LEN)
    if nospecs:
        prompt = (
            f"Ты — редактор блога магазина Паврус (pavrus.ru). Напиши новость-анонс на русском: "
            f"в каталоге представлена позиция бренда PAVRUS «{title}» (категория: {source}). "
            f"СТРОГО {lo}–{hi} символов. ГЛАВНЫЙ ЗАПРЕТ: не выдумывай характеристики, цифры, цены — "
            f"пиши о назначении этого класса оборудования и критериях выбора в общем виде. "
            f"Упоминай только бренд PAVRUS, никаких других брендов. "
            f"Без ссылок и штампов «в современном мире», «стоит отметить», «невероятный»."
        )
    else:
        role = "полноценную SEO-статью" if kind == "article" else "короткую новость-анонс"
        prompt = (
            f"Ты — редактор блога интернет-магазина Паврус (pavrus.ru). Напиши {role} на русском "
            f"о товаре бренда PAVRUS: «{title}».\n"
            f"Источник фактов (перескажи своими словами):\n{source[:6000]}\n"
            f"Требования: 1) Объём СТРОГО {lo}–{hi} символов. "
            f"2) {'Лид, 2–3 подзаголовка, вывод.' if kind == 'article' else 'Лид, 1–2 абзаца фактов, финальная фраза.'} "
            f"3) ЗАПРЕТ штампов: «в современном мире», «стоит отметить», «данное изделие», «невероятный». "
            f"4) Только факты из источника. 5) Без ссылок, цен, e-mail. "
            f"6) Упоминай только бренд PAVRUS, не сравнивай с другими брендами."
        )
    return ai_generate(prompt, int(lo * 0.9), int(hi * 1.1))

# ============================================================
# DOCX
# ============================================================
def make_docx(title, body, kind):
    if not HAS_DOCX:
        log("❌ python-docx не установлен — .docx создать невозможно")
        return None
    safe = re.sub(r"[^\w\-]+", "_", title).strip("_")[:80] or "article"
    path = f"article_{datetime.date.today().isoformat()}_{safe}.docx"
    try:
        doc = Document()
        doc.add_heading(title, level=1)
        doc.add_paragraph(f"Бренд: {BRAND} | Тип: {kind} | Дата: {datetime.date.today().strftime('%d.%m.%Y')}")
        for block in body.split("\n"):
            block = block.strip()
            if not block:
                continue
            if len(block) < 90 and not block.endswith((".", "!", "?")):
                doc.add_heading(block, level=2)
            else:
                doc.add_paragraph(block)
        doc.save(path)
        log(f"📄 Создан файл: {path}")
        return path
    except Exception as e:
        log(f"❌ Ошибка создания .docx: {e}")
        return None

# ============================================================
# ПОЧТА С ВЛОЖЕНИЕМ
# ============================================================
def send_email(subject, note_text, docx_path, source_url):
    recipients = [r.strip() for r in RECIPIENTS.split(",") if r.strip()]
    if not (SMTP_HOST and SMTP_LOGIN and SMTP_PASSWORD and recipients):
        log("⚠️ SMTP не настроен — письмо не отправлено")
        return False
    if not (docx_path and os.path.exists(docx_path)):
        log("⚠️ Нет файла .docx — письмо не отправлено")
        return False
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or SMTP_LOGIN
    msg["To"] = ", ".join(recipients)
    note = note_text + f"\n\nИсточник: {source_url}"
    msg.attach(MIMEText(note, "plain", "utf-8"))
    with open(docx_path, "rb") as f:
        part = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(docx_path)}"')
    msg.attach(part)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=60) as s:
            s.login(SMTP_LOGIN, SMTP_PASSWORD)
            s.sendmail(msg["From"], recipients, msg.as_string())
        log(f"✅ Письмо отправлено: {len(recipients)} получ. + вложение {os.path.basename(docx_path)}")
        return True
    except Exception as e:
        log(f"⚠️ SMTP ошибка: {e}")
        return False

# ============================================================
# ГЛАВНЫЙ ЦИКЛ
# ============================================================
def main():
    browser = Browser()
    browser.start()

    addresses = get_addresses(browser)
    # ФИЛЬТР БРЕНДА: только товары PAVRUS
    addresses = [u for u in addresses if is_pavrus_brand(u)]
    log(f"🏷 После фильтра бренда PAVRUS: {len(addresses)} адресов")
    if not addresses:
        log("❌ Нет адресов бренда PAVRUS — выход")
        browser.close()
        raise SystemExit(1)

    candidates = pick_candidates(addresses)
    failed_list = load_json(FAILED_FILE, [])
    used_list = load_json(USED_FILE, [])
    history = load_json(HISTORY_FILE, [])

    live_dead = False
    sent = False
    for url in candidates:
        name0, cat0 = slug_to_name(url)

        page = wayback_latest(url)
        label = "wayback"
        if not page and not live_dead:
            page = fetch_smart(browser, url)
            label = "live"
            if page is None:
                live_dead = True
                log("⚠️ Живой сайт закрыт KillBot — больше не дёргаю его в этом запуске")
        if not page or is_killbot(page):
            page = fetch_archive_today(url)
            label = "archive.today"

        title, text, specs = "", "", []
        if page and not is_killbot(page):
            title, text, specs = extract_page(page)
            log(f"🔎 [{label}] {url}: текст {len(text)} симв., характеристик {len(specs)}")

        source = text
        nospecs = False
        if len(source) < MIN_SOURCE and specs:
            source = f"{title}. Характеристики: " + "; ".join(specs)
        if len(source) < MIN_SOURCE:
            snips = ddg_source(title or name0)
            if snips:
                source = f"{title or name0}. По данным открытых источников: " + " ".join(snips)
                label += "+snippets"
        if len(source) < MIN_SOURCE:
            if FALLBACK_NEWS:
                log(f"⚠️ Ни одной копии не найдено → анонс по названию: «{name0}»")
                title, source, nospecs = name0, cat0, True
                label = "name-fallback"
            else:
                if url not in failed_list:
                    failed_list.append(url)
                continue

        kind = "article" if (len(source) >= 600 and not nospecs) else "news"
        log(f"📝 Источник: {label} | тип: {kind} | {len(source)} симв.")
        body = build_text(title or name0, source, kind, nospecs=nospecs)
        if not body:
            log("⚠️ ИИ не уложился в длину — следующий кандидат")
            continue

        docx_path = make_docx(title or name0, body, kind)
        if not docx_path:
            continue

        note = (f"Добрый день!\n\nВо вложении — новая {('статья' if kind == 'article' else 'новость')} "
                f"для сайта pavrus.ru.\nТема: {title or name0}\nБренд: {BRAND}\n"
                f"\n— Агент статей Паврус (автоматическая отправка)")
        if send_email(f"Статья для pavrus.ru: {title or name0}"[:120], note, docx_path, url):
            sent = True
            if url not in used_list:
                used_list.append(url)
            history.append({"date": datetime.date.today().isoformat(), "url": url,
                            "kind": kind, "title": title or name0, "source": label})
            break

    browser.close()
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
