# -*- coding: utf-8 -*-
import os, re, json, html, random, sys, io, time, datetime, requests, urllib3
from PIL import Image
urllib3.disable_warnings()

VK_TOKEN = os.environ.get("VK_TOKEN", "").strip()            # групповой токен — посты
VK_USER_TOKEN = os.environ.get("VK_USER_TOKEN", "").strip()  # пользовательский — загрузка фото
VK_GROUP_ID = os.environ.get("VK_GROUP_ID", "").strip().lstrip("-")
TG_BOT = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
OR_KEY = os.environ.get("OPENROUTER_KEY", "").strip()

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "history_vk.json"
API = "https://api.vk.com/method/"
VK_V = "5.131"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
BRANDS = ["pavrus", "chartu", "restmoment", "htdz"]
BL = ["корзин", "кабинет", "избранн", "сравнени", "войти", "заказать звонок",
      "санкт-петербург", "москва", "новосибирск", "8 (800", "info@", "показать еще",
      "ваш город", "бесплатная доставка", "главная", "обратная связь", "каталог"]

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

log("Версия ℹ️ pavrus-vk-agent v3 (товар → ВК sblgroup + карточка в TG; отбор по H1, фото не мельче 600px)")

# ============================================================
# ИИ
# ============================================================

def _extract(r):
    try: return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError): return None

def ai_groq(prompt):
    if not GROQ_KEY: return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": "llama-3.3-70b-versatile", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
            timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_openrouter(prompt, model):
    if not OR_KEY: return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}", "HTTP-Referer": "https://github.com"},
            json={"model": model, "temperature": 0.8, "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt + "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."}]},
            timeout=60).json()
        if "error" in r: return None
        return _extract(r)
    except Exception: return None

def ai_call(prompt, minlen=400):
    models = [
        ("groq", "llama-3.3-70b-versatile"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("openrouter", "google/gemma-3-27b-it:free"),
        ("openrouter", "deepseek/deepseek-chat-v3-0324:free"),
        ("openrouter", "auto")
    ]
    for provider, model in models:
        try:
            log(f"🔄 Попытка: {provider} ({model})...")
            res = ai_groq(prompt) if provider == "groq" else ai_openrouter(prompt, model)
            if res and len(res) >= minlen:
                log(f"✅ Успех: {provider} ({model}), {len(res)} симв.")
                return res
        except Exception:
            pass
    return None

# ============================================================
# ХЕЛПЕРЫ
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

def get_h1(r):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", r, re.S | re.I)
    return clean(m.group(1)) if m else ""

def get_meta(r, name):
    for pat in (
        r'<meta[^>]+name=["\']' + name + r'["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']' + name + r'["\']',
    ):
        m = re.search(pat, r, re.S | re.I)
        if m:
            v = clean(m.group(1))
            if v: return v
    return ""

def get_og_image(r):
    for pat in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']',
    ):
        m = re.search(pat, r, re.S | re.I)
        if m:
            u = abs_url(m.group(1))
            if u: return u
    return ""

# ============================================================
# СБОР И ВЫБОР СТРАНИЦЫ
# ============================================================

def collect_urls():
    urls = []
    try:
        log("Этап 1: карта сайта...")
        xml = requests.get(SITEMAP, timeout=30, headers=UA).text
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
        smps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
        for sm in smps:
            try:
                x = requests.get(sm, timeout=30, headers=UA).text
            except Exception:
                continue
            urls += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x) if "/catalog/" in u]
    except Exception as e:
        log(f"⚠️ sitemap: {e}")
    urls = sorted(set(urls))
    log(f"ℹ️ Ссылок /catalog/: {len(urls)}")
    if len(urls) < 10:
        for s in CATEGORY_SEEDS:
            try:
                h = requests.get(s, timeout=20, headers=UA).text
            except Exception:
                continue
            for href in re.findall(r'href=["\'](/catalog/[^"\']+)["\']', h):
                u = abs_url(href)
                if u and u not in urls:
                    urls.append(u)
        urls = sorted(set(urls))
    def brand_rank(u):
        return 0 if any(b in u.lower() for b in BRANDS) else 1
    urls.sort(key=brand_rank)
    return urls

def parse_page(r, h1):
    desc = get_meta(r, "description") or get_meta(r, "og:description")
    tail = re.sub(r"<script[^>]*>.*?</script>", " ", r, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    for mk in ["Назад к списку", "Нужна консультация", "Подробная информация"]:
        i = tail.find(mk)
        if i != -1:
            tail = tail[:i]
    chunks = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
    chunks += re.findall(r'<div[^>]+class=["\'][^"\']*(?:descr|text|content|detail|char)[^"\']*["\'][^>]*>(.*?)</div>', tail, re.S | re.I)
    raw = " ".join(clean(c) for c in chunks)
    keep = [s.strip() for s in raw.split(". ")
            if len(s.strip()) > 30 and "{" not in s
            and not any(b in s.lower() for b in BL)]
    body = " ".join(keep)[:1500]
    imgs = []
    og = get_og_image(r)
    if og: imgs.append(og)
    for tag in re.findall(r"<img[^>]+>", tail)[:15]:
        u = ""
        for attr in ("data-src", "data-lazy-src", "data-original", "src"):
            am = re.search(attr + r'\s*=\s*["\']([^"\']+)["\']', tag, re.I)
            if am and am.group(1).strip():
                u = am.group(1)
                break
        u = abs_url(u.split(",")[0].strip().split(" ")[0])
        if u and u not in imgs and not any(x in u.lower() for x in ("logo", "svg", "icon", "banner")):
            imgs.append(u)
    return desc, body, imgs

def pick_page(urls, hist):
    for attempt in range(25):
        available = [u for u in urls if u not in hist]
        if not available:
            log("ℹ️ История полная — начинаю круг заново")
            available = urls
        page = random.choice(available[:300])
        try:
            r = requests.get(page, timeout=30, headers=UA).text
        except Exception:
            log(f"⚠️ Попытка {attempt+1}: не открылось — {page}")
            continue
        h1 = get_h1(r)
        if not h1:
            log(f"⚠️ Попытка {attempt+1}: нет H1 — {page}")
            continue
        if not any(b in h1.lower() for b in BRANDS):
            log(f"⚠️ Попытка {attempt+1}: в H1 нет бренда («{h1[:50]}») — {page}")
            continue
        desc, body, imgs = parse_page(r, h1)
        if len(body) + len(desc) < 40:
            log(f"⚠️ Попытка {attempt+1}: мало текста — {page}")
            continue
        log(f"✅ Попытка {attempt+1}: товар «{h1[:70]}» — {page}")
        return page, h1, desc, body, imgs
    return None, "", "", "", []

# ============================================================
# ФОТО: только нормальные размеры (никаких логотипов 226x59)
# ============================================================

def choose_image(imgs):
    best, best_px = None, 0
    for u in imgs[:8]:
        try:
            rs = requests.get(u, timeout=30, headers=UA)
            if not rs.headers.get("content-type", "").startswith("image"):
                continue
            if not (20000 < len(rs.content) < 5000000):
                continue
            im = Image.open(io.BytesIO(rs.content))
            w, h = im.size
            if w < 600 or h < 400:
                continue
            if w * h > best_px:
                best_px, best = w * h, rs.content
        except Exception:
            continue
    if best:
        log(f"✅ Фото товара: {len(best)} байт")
    else:
        log("⚠️ Подходящего фото нет — пост без картинки")
    return best

# ============================================================
# ВК И TG
# ============================================================

def vk_call(method, params, token):
    p = dict(params or {})
    p["access_token"] = token
    p["v"] = VK_V
    try:
        r = requests.post(API + method, data=p, timeout=30).json()
    except Exception as e:
        log(f"⚠️ VK {method}: {e}")
        return None
    if "error" in r:
        log(f"⚠️ VK {method}: {str(r.get('error'))[:150]}")
        return None
    return r.get("response")

def vk_upload(img_bytes):
    tok = VK_USER_TOKEN or VK_TOKEN
    for params in ({"owner_id": "-" + VK_GROUP_ID}, {"group_id": VK_GROUP_ID}):
        srv = vk_call("photos.getWallUploadServer", params, tok)
        if not srv or "upload_url" not in srv:
            continue
        try:
            r = requests.post(srv["upload_url"],
                files={"photo": ("product.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
        except Exception:
            continue
        if "photo" not in r:
            continue
        sp = dict(params)
        sp.update({"photo": r["photo"], "server": r.get("server", ""), "hash": r.get("hash", "")})
        saved = vk_call("photos.saveWallPhoto", sp, tok)
        if saved:
            p = saved[0]
            att = f"photo{p['owner_id']}_{p['id']}"
            if p.get("access_key"):
                att += f"_{p['access_key']}"
            log(f"✅ ВК: фото загружено → {att}")
            return att
    return None

def vk_post(message, att):
    params = {"owner_id": "-" + VK_GROUP_ID, "message": message, "from_group": 1}
    if att:
        params["attachments"] = att
    res = vk_call("wall.post", params, VK_TOKEN)
    if res:
        log(f"✅ ВК: пост опубликован: https://vk.com/wall-{VK_GROUP_ID}_{res.get('post_id')}")
        return True
    return False

def tg_post(img_bytes, caption):
    if not TG_BOT or not TG_CHAT:
        log("ℹ️ TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы — TG пропущен")
        return
    caption = caption[:1020].rstrip()
    if img_bytes:
        r = requests.post(f"https://api.telegram.org/bot{TG_BOT}/sendPhoto",
            data={"chat_id": TG_CHAT, "caption": caption},
            files={"photo": ("product.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
    else:
        r = requests.post(f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
            data={"chat_id": TG_CHAT, "text": caption}, timeout=60).json()
    if r.get("ok"):
        log("✅ TG: карточка товара отправлена")
    else:
        log(f"⚠️ TG: {str(r)[:150]}")

# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================

def main():
    urls = collect_urls()
    try:
        hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
    except Exception:
        hist = set()

    page, title, desc, body, imgs = pick_page(urls, hist)
    if not page:
        log("❌ Не найден товар с брендом в H1")
        sys.exit(1)

    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)

    prompt = (
        f"Напиши пост для сообщества ВКонтакте «Группа SBL» о товаре.\n\n"
        f"ТОВАР: {title}\n"
        f"ОПИСАНИЕ: {desc}\n"
        f"ДЕТАЛИ: {body[:900]}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. 500-900 символов, живо и по-деловому, без капса и кликбейта.\n"
        f"3. Начни с названия товара обычной строкой.\n"
        f"4. Подчеркни применение: конференц-залы, презентации, мероприятия.\n"
        f"5. В конце строка: «Подробнее: {page}»\n"
        f"6. Без хэштегов."
    )
    text = ai_call(prompt, 400)
    if not text:
        text = f"{title}\n\n{desc or body[:600]}\n\nПодробнее: {page}"
    text = text.replace("**", "").replace("##", "").strip()
    if len(text) > 1500:
        text = text[:1500].rsplit(" ", 1)[0].rstrip() + f"\n\nПодробнее: {page}"
    log(f"📝 Текст поста: {len(text)} симв.")

    img = choose_image(imgs)
    att = vk_upload(img) if img else None
    ok = vk_post(text, att)
    if not ok:
        log("❌ ВК: пост не опубликован")
        sys.exit(1)
    tg_post(img, text)

    log("=" * 50)
    log("✅ FINISH: товар → ВК sblgroup (+ TG карточка)!")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
