# -*- coding: utf-8 -*-
import os, re, json, html, random, sys, io, time, datetime, base64, uuid, requests, urllib3
from PIL import Image
urllib3.disable_warnings()

# ============================================================
# КОНФИГУРАЦИЯ (ВСЕ ПРОБЕЛЫ В СТРОКАХ УДАЛЕНЫ)
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

def log(msg):
    print(msg, flush=True)

log("pavrus-vk-agent v40 (без заголовков #, без повтора названия, 1500-2500 симв)")

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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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
        if w >= min_w:
            return img_bytes
        new_w, new_h = min_w, int(h * min_w / w)
        im = im.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    except Exception:
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

    return h1, desc, ". ".join(keep)[:2500]

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
            headers={"Authorization": f"Basic {credentials}", "RqUID": str(uuid.uuid4()), "Content-Type": "application/x-www-form-urlencoded"},
            data={"scope": "GIGACHAT_API_PERS"}, timeout=30, verify=False)
        if r.status_code == 200 and "access_token" in r.json():
            token = r.json()["access_token"]
            r2 = requests.post("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"model": "GigaChat:latest", "temperature": 0.8, "max_tokens": 3000,
                      "messages": [{"role": "user", "content": prompt + "\n\nПиши ТОЛЬКО на русском."}]},
                timeout=90, verify=False)
            if r2.status_code == 200:
                return r2.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None

def ai_call(prompt, minlen=1500):
    res = ai_gigachat(prompt)
    if res and len(res) >= minlen:
        log(f"Успех: gigachat, {len(res)} симв.")
        return res
    log("ИИ не ответил или ответил слишком коротко. Использую фолбэк.")
    return None

# ============================================================
# ВК и TG
# ============================================================
def vk_call(method, params, token):
    p = dict(params or {})
    p["access_token"] = token
    p["v"] = VK_V
    try:
        r = requests.post(API + method, data=p, timeout=30).json()
        return r.get("response") if "error" not in r else None
    except Exception:
        return None

def vk_upload(img_bytes):
    if not VK_USER_TOKEN:
        return None
    srv = vk_call("photos.getWallUploadServer", {"owner_id": "-" + VK_GROUP_ID}, VK_USER_TOKEN)
    if not srv or "upload_url" not in srv:
        return None
    try:
        r = requests.post(srv["upload_url"], files={"photo": ("p.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
        if not r.get("photo"):
            return None
        sp = {"owner_id": "-" + VK_GROUP_ID, "photo": r["photo"], "server": r.get("server", ""), "hash": r.get("hash", "")}
        saved = vk_call("photos.saveWallPhoto", sp, VK_USER_TOKEN)
        if saved:
            p = saved[0]
            att = f"photo{p['owner_id']}_{p['id']}"
            if p.get("access_key"):
                att += f"_{p['access_key']}"
            return att
    except Exception:
        pass
    return None

def vk_post(message, att):
    params = {"owner_id": "-" + VK_GROUP_ID, "message": message, "from_group": 1, "signed": 0}
    if att:
        params["attachments"] = att
    res = vk_call("wall.post", params, VK_TOKEN)
    if res:
        log(f"ВК: пост опубликован: https://vk.com/wall-{VK_GROUP_ID}_{res.get('post_id')}")
        return True
    return False

def tg_post(img_bytes, caption):
    if not TG_BOT or not TG_CHAT:
        return
    caption = caption[:4000].rstrip()  # TG позволяет до 4096 символов
    if img_bytes:
        r = requests.post(f"https://api.telegram.org/bot{TG_BOT}/sendPhoto",
            data={"chat_id": TG_CHAT, "caption": caption},
            files={"photo": ("p.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
    else:
        r = requests.post(f"https://api.telegram.org/bot{TG_BOT}/sendMessage",
            data={"chat_id": TG_CHAT, "text": caption}, timeout=60).json()
    if r.get("ok"):
        log(f"TG: отправлено в {TG_CHAT}")

# ============================================================
# ГЛАВНАЯ ЛОГИКА
# ============================================================
def main():
    # 1. Читаем локальный кэш
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
        urls = cache.get("urls", [])
        if not urls:
            log("Файл sitemap_cache.json пуст.")
            sys.exit(1)
        log(f"Использован локальный кэш: {len(urls)} ссылок")
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

    # 2. Инициализируем Playwright
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
            log(f"Найден товар: {title[:60]}")
            break

    pw_close()

    if not page:
        log("Не найдена подходящая страница")
        sys.exit(1)

    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False)

    # 3. Генерация текста БЕЗ ЗАГОЛОВКОВ, БЕЗ ПОВТОРА НАЗВАНИЯ, 1500-2500 символов
    prompt = (
        f"Напиши развернутую экспертную статью о товаре для Яндекс.Дзен и ВКонтакте.\n\n"
        f"ТОВАР: {title}\n"
        f"ОПИСАНИЕ: {desc}\n"
        f"ХАРАКТЕРИСТИКИ: {body[:2500]}\n\n"
        f"КРИТИЧЕСКИ ВАЖНЫЕ ТРЕБОВАНИЯ:\n"
        f"1. ТОЛЬКО русский язык.\n"
        f"2. Объем: СТРОГО 1500-2500 символов с пробелами.\n"
        f"3. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО: использовать символы # или * в начале строк (никаких markdown-заголовков).\n"
        f"4. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО: начинать текст с названия товара или повторять его в первой строке.\n"
        f"5. Начни сразу с описательного текста, например: «Современное оборудование для конференц-залов...» или «Профессиональное решение для...».\n"
        f"6. Пиши развернутыми абзацами (2-3 абзаца), экспертным стилем, без тезисов.\n"
        f"7. Подчеркни применение: конференц-залы, презентации, масштабные мероприятия.\n"
        f"8. В конце: «Напишите нам в сообщения группы — расскажем подробнее и подберём решение под ваш проект».\n"
        f"9. БЕЗ хэштегов и ссылок (http, https, www, pavrus.ru)."
    )

    text = ai_call(prompt, 1500)
    if not text:
        text = f"Современное профессиональное оборудование для конференц-залов и масштабных мероприятий.\n\n{desc}\n\n{body[:2000]}\n\nНапишите нам в сообщения группы — расскажем подробнее и подберём решение под ваш проект!"

    # ОЧИСТКА ТЕКСТА
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # Пропускаем строки, начинающиеся с # (markdown заголовки)
        if line.startswith('#'):
            continue
        # Пропускаем строки, которые повторяют название товара (первые 2 строки)
        if len(cleaned_lines) < 2 and title.lower() in line.lower() and len(line) < len(title) + 30:
            continue
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines).strip()
    
    # Удаляем markdown-форматирование
    text = text.replace("**", "").replace("##", "").replace("*", "")
    
    # Удаляем ссылки
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"pavrus\.ru\S*", "", text, flags=re.I)
    text = re.sub(r"Подробнее:\s*", "", text, flags=re.I)
    
    # УМНАЯ ОБРЕЗКА: обрезаем по последнему полному предложению до 2500 символов
    if len(text) > 2500:
        cut_pos = text.rfind('.', 0, 2500)
        if cut_pos > 1500:
            text = text[:cut_pos + 1]
        else:
            cut_pos = text.rfind(' ', 0, 2500)
            if cut_pos > 1500:
                text = text[:cut_pos]
        
        if "Напишите нам" not in text:
            text += "\n\nНапишите нам в сообщения группы — расскажем подробнее!"

    log(f"Текст поста: {len(text)} симв.")

    # 4. Публикация
    att = vk_upload(img) if img else None
    if vk_post(text, att):
        tg_post(img, text)
        log("FINISH: товар -> ВК + TG!")
    else:
        log("ВК: пост не опубликован")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise
