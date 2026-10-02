# -*- coding: utf-8 -*-
import os, re, json, html, random, sys, io, time, datetime, base64, uuid, requests, urllib3
from PIL import Image
urllib3.disable_warnings()

# ============================================================
# КОНФИГУРАЦИЯ (ВСЕ ПРОБЕЛЫ ВНУТРИ КАВЫЧЕК УДАЛЕНЫ)
# ============================================================
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
GIGACHAT_CLIENT_ID = os.environ.get("GIGACHAT_CLIENT_ID1", "").strip()
GIGACHAT_CLIENT_SECRET = os.environ.get("GIGACHAT_CLIENT_SECRET1", "").strip()

SITE = "https://pavrus.ru"
HISTORY = "history_vk.json"
CACHE = "sitemap_cache.json"
API = "https://api.vk.com/method/"
VK_V = "5.131"

BRAND_SLUGS = ["pavrus", "htdz", "ht-dz", "chartu", "restmoment", "rest-moment"]
BL = ["корзин", "кабинет", "избранн", "сравнени", "войти", "заказать звонок",
      "санкт-петербург", "москва", "новосибирск", "8 (800", "info@", "показать еще",
      "ваш город", "бесплатная доставка", "главная", "обратная связь",
      "выбрано максимальное", "доступное для заказа", "количество товара",
      "цена:", "руб", "₽", "купить", "оформить заказ", "в наличии", "под заказ",
      "артикул", "арт.", "гаранти", "доставк", "cookie", "политик"]

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

def log(msg):
    print(msg, flush=True)

log("pavrus-vk-agent v52 (Playwright, локальный кэш, ОДИН пост, АНТИ-НЕЙРОСЛОП)")

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

def pw_get_image(url, referer):
    if not _pw_context:
        return None
    try:
        resp = _pw_context.request.get(url, headers={"Referer": referer})
        if resp.ok and len(resp.body()) > 5000:
            return resp.body()
    except Exception:
        pass
    return None

def pw_close():
    global _pw_browser, _pw_context
    try:
        if _pw_browser:
            _pw_browser.close()
    except Exception:
        pass

# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def clean(s):
    for _ in range(3):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def brand_in_url(u):
    path = u.split("//", 1)[-1].split("/", 1)[-1].lower()
    return any(b in path for b in BRAND_SLUGS)

def ensure_size(img_bytes, min_w=1000):
    try:
        im = Image.open(io.BytesIO(img_bytes))
        w, h = im.size
        log(f"Исходный размер картинки: {w}x{h}px")
        if w >= min_w:
            log(f"Размер достаточный (>= {min_w}px)")
            return img_bytes
        new_w, new_h = min_w, int(h * min_w / w)
        im = im.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        log(f"Картинка увеличена с {w}x{h} до {new_w}x{new_h}px")
        return buf.getvalue()
    except Exception as e:
        log(f"ensure_size ошибка: {e}")
        return img_bytes

def parse_text(r):
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", r, re.S | re.I)
    if m:
        h1 = clean(m.group(1))
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
            if desc:
                break

    tail = re.sub(r"<script[^>]*>.*?</script>", " ", r, flags=re.S | re.I)
    tail = re.sub(r"<style[^>]*>.*?</style>", " ", tail, flags=re.S | re.I)
    chunks = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
    raw = " ".join(clean(c) for c in chunks)

    seen = set()
    keep = []
    for s in raw.split(". "):
        s = s.strip()
        if len(s) < 30 or "{" in s:
            continue
        low = s.lower()
        if any(b in low for b in BL) or low in seen:
            continue
        seen.add(low)
        keep.append(s)

    return h1, desc, ". ".join(keep)[:2000]

def parse_gallery(r):
    out, seen = [], set()
    for m in re.finditer(r'<(?:a|div|img)[^>]+class="[^"]*catalog-element-gallery-picture[^"]*"[^>]*>', r, re.I):
        for attr in ("href", "data-src", "src"):
            am = re.search(attr + r'\s*=\s*["\']([^"\']+)["\']', m.group(0), re.I)
            if am and am.group(1).strip():
                u = am.group(1).split(",")[0].strip().split(" ")[0]
                if u.startswith("//"):
                    u = "https:" + u
                elif u.startswith("/"):
                    u = SITE + u
                if u not in seen:
                    seen.add(u)
                    out.append(u)
                break
    return out

def choose_image(imgs, referer):
    best, best_px = None, 0
    for u in imgs[:15]:
        img_data = pw_get_image(u, referer)
        if not img_data:
            try:
                rs = requests.get(u, timeout=20, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
                if rs.status_code == 200 and len(rs.content) > 5000:
                    img_data = rs.content
            except Exception:
                continue
        if img_data:
            try:
                im = Image.open(io.BytesIO(img_data))
                if im.size[0] >= 400 and im.size[1] >= 300 and im.size[0] * im.size[1] > best_px:
                    best_px, best = im.size[0] * im.size[1], img_data
            except Exception:
                continue
    return best

# ============================================================
# ИИ-ТЕКСТ
# ============================================================
def ai_gigachat(prompt):
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        return None
    try:
        credentials = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode()).decode()
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={"Authorization": f"Basic {credentials}", "RqUID": str(uuid.uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"scope": "GIGACHAT_API_PERS"}, timeout=30, verify=False)
        if r.status_code == 200 and "access_token" in r.json():
            token = r.json()["access_token"]
            r2 = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"model": "GigaChat:latest", "temperature": 0.8, "max_tokens": 2000,
                      "messages": [{"role": "user", "content": prompt + "\n\nПиши ТОЛЬКО на русском."}]},
                timeout=90, verify=False)
            if r2.status_code == 200:
                return r2.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None

def ai_call(prompt, minlen=700):
    res = ai_gigachat(prompt)
    if res and len(res) >= minlen:
        log(f"Успех: gigachat, {len(res)} симв.")
        return res
    log("ИИ не ответил или ответил слишком коротко.")
    return None

# ============================================================
# ВК (с защитой от Flood Control)
# ============================================================
def vk_call(method, params, token, retries=5):
    p = dict(params or {})
    p["access_token"] = token
    p["v"] = VK_V
    for attempt in range(retries):
        try:
            r = requests.post(API + method, data=p, timeout=30).json()
            if "error" in r:
                err = r["error"]
                if err.get("error_code") == 9:
                    delay = 10 * (attempt + 1)
                    log(f"VK Flood control. Ждем {delay} сек (попытка {attempt+1}/{retries})...")
                    time.sleep(delay)
                    continue
                log(f"VK {method} error: {err}")
                return None
            return r.get("response")
        except Exception as e:
            log(f"VK {method} exception: {e}")
            time.sleep(5)
    log(f"VK {method}: все {retries} попыток исчерпаны")
    return None

def vk_upload(img_bytes):
    if not VK_USER_TOKEN:
        log("VK_USER_TOKEN не задан!")
        return None
    if not img_bytes:
        log("Нет данных картинки для загрузки!")
        return None

    log(f"Загрузка фото в ВК: {len(img_bytes)} байт")
    try:
        im = Image.open(io.BytesIO(img_bytes))
        log(f"Формат: {im.format}, Размер: {im.size[0]}x{im.size[1]}, Режим: {im.mode}")
        if im.mode != 'RGB':
            im = im.convert('RGB')
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=90)
            img_bytes = buf.getvalue()
            log("Конвертировано в RGB/JPEG")
    except Exception as e:
        log(f"Ошибка проверки картинки: {e}")

    srv = vk_call("photos.getWallUploadServer", {"owner_id": "-" + VK_GROUP_ID}, VK_USER_TOKEN, retries=5)
    if not srv or "upload_url" not in srv:
        log("Не получен upload server URL после 5 попыток")
        return None

    for attempt in range(3):
        try:
            r = requests.post(srv["upload_url"],
                             files={"photo": ("product.jpg", img_bytes, "image/jpeg")},
                             timeout=120)
            r_json = r.json()
            if not r_json.get("photo"):
                log(f"Пустое photo в ответе (попытка {attempt+1}): {r_json}")
                if attempt < 2:
                    time.sleep(10 * (attempt + 1))
                    continue
                return None

            sp = {"owner_id": "-" + VK_GROUP_ID,
                  "photo": r_json["photo"],
                  "server": r_json.get("server", ""),
                  "hash": r_json.get("hash", "")}

            saved = vk_call("photos.saveWallPhoto", sp, VK_USER_TOKEN, retries=5)
            if saved:
                p = saved[0]
                att = f"photo{p['owner_id']}_{p['id']}"
                if p.get("access_key"):
                    att += f"_{p['access_key']}"
                log(f"Фото загружено: {att}")
                return att
            else:
                log("photos.saveWallPhoto вернул None")
                return None
        except Exception as e:
            log(f"Ошибка загрузки фото (попытка {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return None

def vk_post(message, att):
    log(f"Публикация в ВК: {len(message)} симв., attachment: {att}")
    params = {"owner_id": "-" + VK_GROUP_ID, "message": message, "from_group": 1, "signed": 0}
    if att:
        params["attachments"] = att
        log(f"Attachment: {att}")
    else:
        log("Публикуем БЕЗ фото!")

    res = vk_call("wall.post", params, VK_TOKEN, retries=5)
    if res:
        log(f"ВК: пост опубликован: https://vk.com/wall-{VK_GROUP_ID}_{res.get('post_id')}")
        return True
    else:
        log("wall.post вернул None")
        return False

def tg_post(img_bytes, caption):
    """ОДНО сообщение с фото. Лимит подписи Telegram = 1024 символа."""
    if not TG_BOT or not TG_CHAT:
        log("TG не настроен (нет токена или chat_id)")
        return

    log(f"Отправка в TG: {len(caption)} симв., фото: {len(img_bytes) if img_bytes else 0} байт")

    max_len = 1000
    if len(caption) > max_len:
        cut_pos = caption.rfind('.', 0, max_len)
        if cut_pos > 800:
            caption = caption[:cut_pos + 1]
        else:
            cut_pos = caption.rfind(' ', 0, max_len)
            if cut_pos > 800:
                caption = caption[:cut_pos]
        log(f"Текст обрезан до {len(caption)} симв. (лимит TG 1024)")

    if img_bytes:
        r = requests.post(f"https://api.telegram.org/bot{TG_BOT}/sendPhoto",
            data={"chat_id": TG_CHAT, "caption": caption},
            files={"photo": ("product.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
    else:
        r = requests.post(f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
            data={"chat_id": TG_CHAT, "text": caption}, timeout=60).json()

    if r.get("ok"):
        log(f"TG: отправлено в {TG_CHAT}")
    else:
        log(f"TG error: {r}")

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
        log(f"Файл {CACHE} не найден!")
        sys.exit(1)

    cand = [u for u in urls if brand_in_url(u)]
    log(f"URL с брендом: {len(cand)} из {len(urls)}")
    if not cand:
        log("Нет URL с брендами")
        sys.exit(1)

    try:
        hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
    except Exception:
        hist = set()

    avail = [u for u in cand if u not in hist] or cand
    random.shuffle(avail)

    pw_ok = pw_init()
    page = title = desc = body = None
    img = None

    for i, u in enumerate(avail[:12]):
        if pw_ok:
            r_text = pw_get_page(u)
        else:
            try:
                rs = requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                r_text = rs.text if rs.status_code == 200 else None
            except Exception:
                r_text = None

        if not r_text or len(r_text) < 3000:
            continue
        if "beget=begetok" in r_text:
            log(f"Заглушка Beget на {u}")
            continue

        title, desc, body = parse_text(r_text)
        if not title or (len(body) + len(desc)) < 40:
            continue

        imgs = parse_gallery(r_text)
        img = choose_image(imgs, u) if imgs else None

        if img:
            img = ensure_size(img, 1000)
            page = u
            log(f"Товар: {title[:60]}")
            break

    pw_close()

    if not page:
        log("Не найдена подходящая страница")
        sys.exit(1)

    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)

    prompt = (
        f"Напиши пост о товаре для ВКонтакте, Telegram и Дзена.\n\n"
        f"ТОВАР: {title}\n"
        f"ОПИСАНИЕ: {desc}\n"
        f"ХАРАКТЕРИСТИКИ: {body[:1500]}\n\n"
        f"ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Объем: СТРОГО 900-1000 символов с пробелами (не больше 1020!).\n"
        f"3. НЕ начинай текст с названия товара — начинай сразу с описания или сценария применения.\n"
        f"4. БЕЗ заголовков # и markdown.\n"
        f"5. 1-2 абзаца, живой экспертный стиль.\n"
        f"6. Подчеркни применение: конференц-залы, презентации, мероприятия.\n"
        f"7. В конце: «Напишите нам в сообщения группы — расскажем подробнее».\n"
        f"8. БЕЗ хэштегов и ссылок (http, https, www, pavrus.ru).\n"
        f"9. 🛡️ АНТИ-НЕЙРОСЛОП: ЗАПРЕЩЕНО использовать слова: 'инновационный', 'революционный', 'в современном мире', 'стоит отметить', 'важно понимать', 'безусловно', 'играет ключевую роль', 'представляет собой', 'является'. Пиши как живой эксперт-практик."
    )

    text = ai_call(prompt, 700)
    if not text:
        text = f"Современное оборудование для конференц-залов и масштабных мероприятий.\n\n{desc}\n\nНапишите нам в сообщения группы — расскажем подробнее!"

    text = clean_slop(text)
    text = text.replace("**", "").replace("##", "").strip()
    text = re.sub(r"^#.*\n", "", text, flags=re.M)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"pavrus\.ru\S*", "", text, flags=re.I)
    text = re.sub(r"Подробнее:\s*", "", text, flags=re.I)

    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if len(cleaned) == 0 and title.lower() in line.lower() and len(line) < len(title) + 30:
            continue
        cleaned.append(line)
    text = '\n'.join(cleaned).strip()

    if len(text) > 1000:
        cut_pos = text.rfind('.', 0, 1000)
        if cut_pos > 800:
            text = text[:cut_pos + 1]
        else:
            cut_pos = text.rfind(' ', 0, 1000)
            if cut_pos > 800:
                text = text[:cut_pos]

    if "Напишите нам" not in text:
        text += "\n\nНапишите нам в сообщения группы — расскажем подробнее!"

    log(f"Текст поста: {len(text)} симв.")

    att = vk_upload(img) if img else None
    log(f"Attachment для ВК: {att if att else 'None'}")

    if vk_post(text, att):
        log("ВК: опубликовано успешно!")
        tg_post(img, text)
    else:
        log("ВК: публикация не удалась")
        sys.exit(1)

    log("=" * 50)
    log("FINISH: товар -> ВК + TG (один пост)")
    log("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        log(traceback.format_exc())
        raise
