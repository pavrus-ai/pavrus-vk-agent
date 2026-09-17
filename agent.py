# -*- coding: utf-8 -*-
import os, re, json, html, random, sys, io, time, datetime, base64, uuid, requests, urllib3
from PIL import Image
urllib3.disable_warnings()

VK_TOKEN = os.environ.get("VK_TOKEN", "").strip()
VK_USER_TOKEN = os.environ.get("VK_USER_TOKEN", "").strip()
VK_GROUP_ID = os.environ.get("VK_GROUP_ID", "").strip().lstrip("-")
TG_BOT = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GROQ_KEY = os.environ.get("GROQ_KEY", "").strip()
GROQ_KEY2 = os.environ.get("GROQ_KEY2", "").strip()
OR_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
OR_KEY2 = os.environ.get("OPENROUTER_KEY2", "").strip()
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "").strip()
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "").strip()
OPENAI_KEY = os.environ.get("OPENAI_KEY", "").strip()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
# Ключи GigaChat НОВОГО аккаунта — только для товарного агента
GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID1", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET1", "").strip()

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "history_vk.json"
CACHE = "sitemap_cache.json"
ALBUM_CACHE = "vk_album.json"
CACHE_TTL_DAYS = 7
API = "https://api.vk.com/method/"
VK_V = "5.131"
POLLINATIONS_API = "https://image.pollinations.ai/prompt/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml",
      "Accept-Language": "ru-RU,ru;q=0.9"}
BRAND_SLUGS = ["pavrus", "htdz", "ht-dz", "chartu", "restmoment", "rest-moment"]
BL = ["корзин", "кабинет", "избранн", "сравнени", "войти", "заказать звонок",
      "санкт-петербург", "москва", "новосибирск", "8 (800", "info@", "показать еще",
      "ваш город", "бесплатная доставка", "главная", "обратная связь",
      "выбрано максимальное", "доступное для заказа", "количество товара",
      "цена:", " руб", "₽", "купить", "оформить заказ", "в наличии", "под заказ",
      "артикул", "арт.", "гаранти", "доставк", "cookie", "политик"]

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

log("Версия ℹ️ pavrus-vk-agent v31 (uuid-фикс GigaChat; groq: llama-4/gpt-oss; openrouter auto с малыми max_tokens; без github-models)")

# ============================================================
# ИИ-ТЕКСТ: ступени с диагностикой
# ============================================================

def _extract(r):
    try: return r["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError): return None

def _err_snippet(r):
    e = r.get("error") or {}
    code = e.get("code") or e.get("type") or "?"
    msg = str(e.get("message") or e)
    return f"{code}: {msg[:100]}"

RU_SUFFIX = "\n\nВАЖНО: Пиши ТОЛЬКО на русском языке."

# ------------------------------------------------------------
# GigaChat (ключи нового аккаунта)
# ------------------------------------------------------------

_GIGACHAT_TOKEN = None
_GIGACHAT_TOKEN_EXPIRY = 0

def get_gigachat_token():
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
            timeout=30, verify=False)
        log(f"ℹ️ GigaChat OAuth: статус {r.status_code}")
        if r.status_code != 200:
            log(f"⚠️ GigaChat OAuth тело: {r.text[:300]}")
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
            json={"model": "GigaChat:latest", "temperature": 0.8, "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]},
            timeout=90, verify=False)
        if r.status_code != 200:
            log(f"⚠️ GigaChat chat: статус {r.status_code}: {r.text[:200]}")
            return None
        res = r.json()["choices"][0]["message"]["content"].strip()
        if res:
            return res
    except Exception as e:
        log(f"⚠️ GigaChat error: {e}")
    return None

# ------------------------------------------------------------
# Остальные провайдеры
# ------------------------------------------------------------

def ai_cerebras(prompt):
    if not CEREBRAS_KEY: return None
    try:
        r = requests.post("https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_KEY}"},
            json={"model": "llama-3.3-70b", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ cerebras: {_err_snippet(r)}")
            return None
        return _extract(r)
    except Exception as e:
        log(f"   ⚠️ cerebras: сеть/ошибка {str(e)[:80]}")
        return None

def ai_mistral(prompt):
    if not MISTRAL_KEY: return None
    try:
        r = requests.post("https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_KEY}"},
            json={"model": "mistral-small-latest", "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ mistral: {_err_snippet(r)}")
            return None
        return _extract(r)
    except Exception as e:
        log(f"   ⚠️ mistral: сеть/ошибка {str(e)[:80]}")
        return None

def ai_groq(prompt, key, model):
    if not key: return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.8,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ groq {model}: {_err_snippet(r)}")
            return None
        return _extract(r)
    except Exception as e:
        log(f"   ⚠️ groq {model}: сеть/ошибка {str(e)[:80]}")
        return None

def ai_openrouter(prompt, key, max_tokens):
    if not key: return None
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com"},
            json={"model": "auto", "temperature": 0.8, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt + RU_SUFFIX}]}, timeout=60).json()
        if "error" in r:
            log(f"   ⚠️ openrouter auto (max={max_tokens}): {_err_snippet(r)}")
            return None
        return _extract(r)
    except Exception as e:
        log(f"   ⚠️ openrouter auto: сеть/ошибка {str(e)[:80]}")
        return None

GROQ_MODELS = ["meta-llama/llama-4-scout-17b-16e-instruct",
               "meta-llama/llama-4-maverick-17b-128e-instruct",
               "openai/gpt-oss-120b",
               "llama-3.1-8b-instant"]

def ai_call(prompt, minlen=400):
    """v31: GigaChat → cerebras → mistral → groq(новые модели) → openrouter auto (малые max_tokens)."""
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

    # 1) GigaChat
    if not GIGACHAT_CLIENT_ID:
        log("⚠️ gigachat: GIGACHAT_CLIENT_ID1 не передан в env!")
    else:
        log("🔄 Попытка: gigachat (GigaChat:latest)...")
        r = take(ai_gigachat(prompt), "gigachat")
        if r: return r
    # 2) Cerebras
    if not CEREBRAS_KEY:
        log("⚠️ cerebras: CEREBRAS_KEY не передан в env!")
    else:
        log("🔄 Попытка: cerebras (llama-3.3-70b)...")
        r = take(ai_cerebras(prompt), "cerebras")
        if r: return r
    # 3) Mistral
    if not MISTRAL_KEY:
        log("⚠️ mistral: MISTRAL_KEY не передан в env!")
    else:
        log("🔄 Попытка: mistral (mistral-small)...")
        r = take(ai_mistral(prompt), "mistral")
        if r: return r
    # 4) Groq с актуальными моделями
    for i, key in enumerate((GROQ_KEY, GROQ_KEY2)):
        if not key: continue
        for model in GROQ_MODELS:
            log(f"🔄 Попытка: groq ({model}, ключ {i+1})...")
            r = take(ai_groq(prompt, key, model), f"groq ({model}, ключ {i+1})")
            if r: return r
    # 5) OpenRouter auto с уменьшенными max_tokens (экономия кредитов)
    for i, key in enumerate((OR_KEY, OR_KEY2)):
        if not key: continue
        for mt in (1000, 512):
            log(f"🔄 Попытка: openrouter auto (max_tokens={mt}, ключ {i+1})...")
            r = take(ai_openrouter(prompt, key, mt), f"openrouter auto (max={mt}, ключ {i+1})")
            if r: return r

    if best_res and len(best_res) >= 200:
        log(f"ℹ️ Никто не дал {minlen} симв. — беру лучший кандидат ({len(best_res)} симв.) вместо фолбэка со страницы")
        return best_res
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

def brand_in_url(u):
    path = u.split("//", 1)[-1].split("/", 1)[-1].lower()
    return any(b in path for b in BRAND_SLUGS)

def ensure_size(img_bytes, min_w=1000):
    try:
        im = Image.open(io.BytesIO(img_bytes))
        w, h = im.size
        if w >= min_w:
            log(f"ℹ️ Размер фото {w}x{h} — увеличение не нужно")
            return img_bytes
        new_w, new_h = min_w, int(h * min_w / w)
        im = im.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        log(f"🔍 Фото увеличено с {w}x{h} до {new_w}x{new_h} (для обложки Дзена)")
        return buf.getvalue()
    except Exception as e:
        log(f"⚠️ ensure_size: {e}")
        return img_bytes

def strip_watermark(img_bytes):
    try:
        im = Image.open(io.BytesIO(img_bytes))
        w, h = im.size
        cut = int(h * 0.09)
        im = im.crop((0, 0, w, h - cut))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=90)
        log(f"✂️ Водяной знак: срезана нижняя полоса {cut}px (было {w}x{h}, стало {im.size[0]}x{im.size[1]})")
        return buf.getvalue()
    except Exception as e:
        log(f"⚠️ strip_watermark: {e}")
        return img_bytes

# ============================================================
# КЭШ КАРТЫ САЙТА
# ============================================================

def load_cache():
    try:
        d = json.load(open(CACHE, encoding="utf-8"))
        urls, ts = d.get("urls", []), d.get("ts", 0)
        age = (time.time() - ts) / 86400
        if urls and age < CACHE_TTL_DAYS:
            log(f"ℹ️ Этап 1: сохранённая карта сайта: {len(urls)} ссылок (возраст {age:.1f} дн.)")
            return urls, False
        log(f"ℹ️ Карта устарела ({age:.1f} дн.) — обновим")
    except Exception:
        log("ℹ️ Кэша карты нет — создадим")
    return [], True

def fetch_sitemap():
    urls = []
    xml = requests.get(SITEMAP, timeout=30, headers=UA).text
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
    smps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
    for sm in smps:
        try:
            x = requests.get(sm, timeout=30, headers=UA).text
        except Exception:
            continue
        urls += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x) if "/catalog/" in u]
    urls = sorted(set(urls))
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
    if not urls:
        raise RuntimeError("пустая карта сайта")
    json.dump({"ts": time.time(), "urls": urls}, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    log(f"✅ Этап 1: карта обновлена: {len(urls)} ссылок")
    return urls

# ============================================================
# ГАЛЕРЕЯ И ТЕКСТ СТРАНИЦЫ
# ============================================================

def parse_gallery(r):
    out, seen = [], set()
    for m in re.finditer(r'<(?:a|div|img)[^>]+class="[^"]*catalog-element-gallery-picture[^"]*"[^>]*>', r, re.I):
        t = m.group(0)
        for attr in ("href", "data-src", "src"):
            am = re.search(attr + r'\s*=\s*["\']([^"\']+)["\']', t, re.I)
            if am and am.group(1).strip():
                u = abs_url(am.group(1).split(",")[0].strip().split(" ")[0])
                if u and u not in seen:
                    seen.add(u)
                    out.append(u)
                break
    log(f"ℹ️ Фото из галереи товара (catalog-element-gallery-picture): {len(out)}")
    return out

def parse_other_imgs(r):
    out = []
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', r, re.S | re.I)
    if og:
        u = abs_url(og.group(1))
        if u: out.append(u)
    for tag in re.findall(r"<img[^>]+>", r)[:20]:
        for attr in ("data-src", "data-lazy-src", "data-original", "src"):
            am = re.search(attr + r'\s*=\s*["\']([^"\']+)["\']', tag, re.I)
            if am and am.group(1).strip():
                u = abs_url(am.group(1).split(",")[0].strip().split(" ")[0])
                if u and u not in out:
                    out.append(u)
                break
    return out

def choose_image(imgs, referer):
    hdr = dict(UA)
    hdr["Referer"] = referer
    hdr["Accept"] = "image/avif,image/webp,image/png,image/*,*/*;q=0.8"
    best, best_px, checked, err_log = None, 0, 0, 0
    for u in imgs[:15]:
        if "resize_cache" in u:
            continue
        try:
            rs = requests.get(u, timeout=20, headers=hdr)
            if rs.status_code == 404:
                if err_log < 3:
                    log(f"   ⚠️ img 404 (нет картинки): {u[:80]}")
                    err_log += 1
                continue
            if rs.status_code != 200:
                if err_log < 3:
                    log(f"   ⚠️ img HTTP {rs.status_code}: {u[:80]}")
                    err_log += 1
                continue
            if len(rs.content) < 5000:
                continue
            im = Image.open(io.BytesIO(rs.content))
            w, h = im.size
            checked += 1
            if w < 400 or h < 300:
                continue
            if w * h > best_px:
                best_px, best = w * h, rs.content
        except Exception as e:
            if err_log < 3:
                log(f"   ⚠️ img ошибка: {u[:80]} ({str(e)[:40]})")
                err_log += 1
            continue
    log(f"ℹ️ Проверено картинок: {checked}, лучшая: {best_px} px")
    if best:
        log(f"✅ Фото товара доступно: {len(best)} байт")
    return best

# ============================================================
# ГЕНЕРАЦИЯ КАРТИНОК: gpt-image-1 → dall-e-3 → HF router → pollinations
# ============================================================

def openai_image(prompt):
    if not OPENAI_KEY:
        return None
    full = prompt + ", photorealistic, high resolution, no text, no logos, no watermark"
    try:
        r = requests.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": full, "n": 1, "size": "1024x1024"},
            timeout=180).json()
        if "error" not in r:
            b64 = (r.get("data") or [{}])[0].get("b64_json")
            if b64:
                data = base64.b64decode(b64)
                log(f"✅ OpenAI gpt-image-1: картинка {len(data)} байт (без водяного знака)")
                return data
        else:
            log(f"⚠️ OpenAI gpt-image-1: {str(r['error'])[:120]}")
    except Exception as e:
        log(f"⚠️ OpenAI gpt-image-1 ошибка: {e}")
    try:
        r = requests.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": full, "n": 1,
                  "size": "1024x1024", "quality": "standard",
                  "response_format": "b64_json"}, timeout=120).json()
        if "error" not in r:
            b64 = (r.get("data") or [{}])[0].get("b64_json")
            if b64:
                data = base64.b64decode(b64)
                log(f"✅ OpenAI DALL-E 3: картинка {len(data)} байт (без водяного знака)")
                return data
        else:
            log(f"⚠️ OpenAI DALL-E 3: {str(r['error'])[:120]}")
    except Exception as e:
        log(f"⚠️ OpenAI ошибка: {e}")
    try:
        r = requests.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": full, "n": 1,
                  "size": "1024x1024", "quality": "standard"}, timeout=120).json()
        url = (r.get("data") or [{}])[0].get("url")
        if url:
            img = requests.get(url, timeout=120).content
            log(f"✅ OpenAI DALL-E 3 (url): картинка {len(img)} байт")
            return img
    except Exception as e:
        log(f"⚠️ OpenAI url ошибка: {e}")
    return None

def hf_image(prompt):
    if not HF_TOKEN:
        return None
    full = prompt + ", photorealistic, high resolution, no text, no logos, no watermark"
    bases = ["https://router.huggingface.co/hf-inference/models/",
             "https://api-inference.huggingface.co/models/"]
    for base in bases:
        for mdl in ("black-forest-labs/FLUX.1-schnell", "black-forest-labs/FLUX.1-dev"):
            try:
                r = requests.post(base + mdl,
                    headers={"Authorization": f"Bearer {HF_TOKEN}"},
                    json={"inputs": full}, timeout=120)
                if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/"):
                    log(f"✅ HF {mdl}: картинка {len(r.content)} байт (без водяного знака)")
                    return r.content
                log(f"⚠️ HF {mdl}: ответ {r.status_code}: {r.text[:80]}")
            except Exception as e:
                log(f"⚠️ HF {mdl} ошибка: {str(e)[:80]}")
    return None

def generate_product_image(title, desc):
    scene = (f"Professional conference hall with modern AV equipment: {title}. "
             f"{desc[:150]} Bright clean interior, warm daylight, sharp focus")
    g = openai_image(scene)
    if g:
        return g
    g = hf_image(scene)
    if g:
        return g
    seed = int(time.time()) % 1000000
    url = (POLLINATIONS_API + requests.utils.quote(scene +
           ", bright vivid colors, photorealistic, no people close-up") +
           f"?nologo=true&seed={seed}&model=flux&width=1280&height=960")
    try:
        r = requests.get(url, timeout=240)
        r.raise_for_status()
        log(f"✅ Сгенерирована картинка промптом (pollinations): {len(r.content)} байт")
        return strip_watermark(r.content)
    except Exception as e:
        log(f"⚠️ Ошибка генерации картинки: {e}")
        return None

def parse_text(r):
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", r, re.S | re.I)
    if m: h1 = clean(m.group(1))
    if not h1:
        m = re.search(r"<title[^>]*>(.*?)</title>", r, re.S | re.I)
        h1 = clean(m.group(1)) if m else ""
        h1 = re.split(r"\s*[—|]\s*", h1)[0].strip()
    desc = ""
    for pat in (r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
                r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']'):
        dm = re.search(pat, r, re.S | re.I)
        if dm:
            desc = clean(dm.group(1))
            if desc: break
    tail = re.sub(r"<script[^>]*>.*?</script>", " ", r, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    for mk in ["Назад к списку", "Нужна консультация", "Подробная информация"]:
        i = tail.find(mk)
        if i != -1:
            tail = tail[:i]
    chunks = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
    chunks += re.findall(r'<div[^>]+class=["\'][^"\']*(?:descr|text|content|detail|char)[^"\']*["\'][^>]*>(.*?)</div>', tail, re.S | re.I)
    raw = " ".join(clean(c) for c in chunks)
    seen = set()
    keep = []
    for s in raw.split(". "):
        s = s.strip()
        s = re.sub(r"^[\s\-+×✕*•·|/\\—–]+", "", s).strip()
        s = re.sub(r"\s{2,}", " ", s)
        if len(s) < 30 or "{" in s:
            continue
        low = s.lower()
        if any(b in low for b in BL):
            continue
        if low in seen:
            continue
        seen.add(low)
        keep.append(s)
    body = ". ".join(keep)[:1500]
    return h1, desc, body

# ============================================================
# ВК: путь 1 (wall server) → путь 2 (альбом, метод photos.save)
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

def vk_get_album_id():
    env_id = os.environ.get("VK_ALBUM_ID", "").strip()
    if env_id.isdigit():
        return int(env_id)
    try:
        d = json.load(open(ALBUM_CACHE, encoding="utf-8"))
        if d.get("album_id"):
            return d["album_id"]
    except Exception:
        pass
    return None

def vk_upload_via_album(img_bytes):
    album = vk_get_album_id()
    if not album:
        log("ℹ️ ВК: путь 2 пропущен (нет VK_ALBUM_ID / vk_album.json)")
        return None
    for tok in (VK_USER_TOKEN, VK_TOKEN):
        if not tok:
            continue
        srv = vk_call("photos.getUploadServer",
                      {"group_id": VK_GROUP_ID, "album_id": album}, tok)
        if not srv or "upload_url" not in srv:
            continue
        try:
            r = requests.post(srv["upload_url"],
                files={"file1": ("product.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
        except Exception:
            continue
        if not r.get("hash") or not r.get("photos_list"):
            log(f"⚠️ ВК upload в альбом: пустой ответ: {str(r)[:120]}")
            continue
        saved = vk_call("photos.save",
                        {"group_id": VK_GROUP_ID, "album_id": album,
                         "server": r.get("server", ""), "photos_list": r.get("photos_list", ""),
                         "hash": r.get("hash", "")}, tok)
        if saved:
            p = saved[0]
            att = f"photo{p['owner_id']}_{p['id']}"
            if p.get("access_key"):
                att += f"_{p['access_key']}"
            return att
    return None

def vk_upload(img_bytes):
    if VK_USER_TOKEN:
        for params in ({"owner_id": "-" + VK_GROUP_ID}, {"group_id": VK_GROUP_ID}):
            srv = vk_call("photos.getWallUploadServer", params, VK_USER_TOKEN)
            if not srv or "upload_url" not in srv:
                continue
            try:
                r = requests.post(srv["upload_url"],
                    files={"photo": ("product.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
            except Exception:
                continue
            if not r.get("photo"):
                log("⚠️ VK upload вернул пустое photo (путь 1) — флуд")
                continue
            sp = dict(params)
            sp.update({"photo": r["photo"], "server": r.get("server", ""), "hash": r.get("hash", "")})
            saved = vk_call("photos.saveWallPhoto", sp, VK_USER_TOKEN)
            if saved:
                p = saved[0]
                att = f"photo{p['owner_id']}_{p['id']}"
                if p.get("access_key"):
                    att += f"_{p['access_key']}"
                log(f"✅ ВК: фото загружено (wall server) → {att}")
                return att
        log("⚠️ ВК: путь 1 недоступен (флуд/токен) — пробую альбом")
    att = vk_upload_via_album(img_bytes)
    if att:
        log(f"✅ ВК: фото загружено (через альбом группы) → {att}")
        return att
    return None

def vk_post(message, att):
    params = {"owner_id": "-" + VK_GROUP_ID, "message": message, "from_group": 1, "signed": 0}
    if att:
        params["attachments"] = att
    res = vk_call("wall.post", params, VK_TOKEN)
    if res:
        log(f"✅ ВК: пост на стене: https://vk.com/wall-{VK_GROUP_ID}_{res.get('post_id')}")
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
        log(f"✅ TG: карточка отправлена в {TG_CHAT}")
    else:
        log(f"⚠️ TG: {str(r)[:200]}")

# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================

def main():
    urls, need_fetch = load_cache()
    if need_fetch:
        try:
            urls = fetch_sitemap()
        except Exception as e:
            log(f"❌ Сайт недоступен и кэша нет: {e} — пропускаю запуск")
            sys.exit(0)

    cand = [u for u in urls if brand_in_url(u)]
    log(f"ℹ️ Этап 2: URL с брендом в адресе: {len(cand)} из {len(urls)}")
    if not cand:
        log("❌ Нет URL с брендами в адресе")
        sys.exit(1)

    try:
        hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
    except Exception:
        hist = set()
    avail = [u for u in cand if u not in hist] or cand
    random.shuffle(avail)

    page = title = desc = body = None
    img = None
    last_ok = None
    site_down = False

    for i, u in enumerate(avail[:12]):
        try:
            rs = requests.get(u, timeout=30, headers=UA)
        except Exception as e:
            log(f"❌ Сайт недоступен (сеть): {u} — {str(e)[:60]}")
            site_down = True
            break
        if rs.status_code == 404:
            log(f"⚠️ Попытка {i+1}: 404 — страница удалена, выбираю другую: {u}")
            continue
        if rs.status_code != 200 or len(rs.text) < 3000:
            log(f"⚠️ Попытка {i+1}: HTTP {rs.status_code} или заглушка — {u}")
            continue
        r = rs.text

        title, desc, body = parse_text(r)
        if not title or (len(body) + len(desc)) < 40:
            log(f"⚠️ Попытка {i+1}: мало текста — {u}")
            continue
        last_ok = (u, title, desc, body)

        imgs = parse_gallery(r) or parse_other_imgs(r)
        img = choose_image(imgs, u) if imgs else None
        if not img:
            log("⚠️ Картинка товара недоступна (404/мелкая) — генерирую (gpt-image-1 → HF → pollinations)")
            img = generate_product_image(title, desc)
        if not img:
            log(f"⚠️ Попытка {i+1}: не удалось получить картинку — {u}")
            continue

        img = ensure_size(img, 1000)
        page = u
        log(f"✅ Попытка {i+1}: товар «{title[:70]}» с картинкой — {page}")
        break

    if site_down:
        log("❌ Сайт pavrus.ru недоступен — агент останавливается без публикации")
        sys.exit(0)

    if not page:
        if last_ok:
            page, title, desc, body = last_ok
            img = None
            log("⚠️ Публикую текстовый пост (картинку получить не удалось)")
        else:
            log("❌ Не найдена подходящая страница")
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
        log("⏳ Все ИИ молчат с первого захода — пауза 30 сек и повторный прогон")
        time.sleep(30)
        text = ai_call(prompt, 400)
    if not text:
        base = body[:900] or desc
        text = f"{title}\n\n{base}\n\nПодробнее: {page}"
        log("⚠️ Все ступени ИИ недоступны — фолбэк из текста страницы")
    text = text.replace("**", "").replace("##", "").strip()
    if len(text) > 1500:
        text = text[:1500].rsplit(" ", 1)[0].rstrip() + f"\n\nПодробнее: {page}"
    log(f"📝 Текст поста: {len(text)} симв.")

    att = vk_upload(img) if img else None
    if not att and img:
        log("⚠️ ВК: пост уйдёт без фото")
    ok = vk_post(text, att)
    if not ok:
        log("❌ ВК: пост не опубликован")
        sys.exit(1)
    tg_post(img, text)

    log("=" * 50)
    log("✅ FINISH: товар → ВК sblgroup + TG → Дзен (обложка ≥700px)!")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
