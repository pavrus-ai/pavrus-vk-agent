
# -*- coding: utf-8 -*-
import os, re, json, html, random, sys
import urllib.parse
import requests

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "history.json"
UA = {"User-Agent": "Mozilla/5.0 (pavrus-vk-agent)"}

VK_TOKEN = os.getenv("VK_TOKEN", "")
VK_USER_TOKEN = os.getenv("VK_USER_TOKEN", "")
VK_GROUP = os.getenv("VK_GROUP_ID", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
OR_KEY = os.getenv("OPENROUTER_KEY", "")
GROQ_KEY = os.getenv("GROQ_KEY", "")

BLACKLIST = ["Корзина", "Кабинет", "Избранные", "Сравнение", "Каталог", "Войти", "Заказать звонок",
             "Санкт-Петербург", "Москва", "Новосибирск", "Краснодар", "Красноярск", "8 (800)", "info@",
             "pavrus.ru", "Показать еще", "Ваш город", "Да, спасибо", "Нет, другой", "Выбрать автоматически",
             "Бесплатная доставка", "Главная", "HTDZ", "AUDAC", "CVID", "CHIAYO", "Restmoment", "радиогид",
             "PAVRUS PA-", "PAVRUS ABK", "E-Desk", "таблички", "громкоговорители", "инфракрасная",
             "@context", "@type", "schema.org", 'description":', "Обратная связь"]

report = []
def log(stage, status, msg):
    line = f"{stage} {status} {msg}"
    print(line, flush=True)
    report.append(line)

def finish():
    if TG_TOKEN and TG_CHAT:
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": "\n".join(report)}, timeout=30)
        except Exception:
            pass

def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()

def good_text(t):
    """Проверка текста: длина, отсутствие JSON и служебных 'мыслей' нейросети."""
    if not t or len(t) < 350:
        return False
    bad = ['"error"', "Payment Required", "pollen", "deprecation_notice", "<html", "<!DOCTYPE", "{", "@context"]
    if t.lstrip().startswith("{") or any(b in t for b in bad):
        return False
    think = ["thinking process", "analyze the request", "constraints:", "**role", "source text:",
             "here's a thinking", "<think>", "additional text:", "1. analyze"]
    if any(tm in t.lower() for tm in think):
        return False
    return True

def good_img(b):
    """Проверка промпта для картинки: не скопировала ли нейросеть инструкцию."""
    if not b or len(b) < 10 or len(b) > 200:
        return False
    lowb = b.lower()
    for bad in ["description in english", "short (10-15", "of how this", "words) description"]:
        if bad in lowb:
            return False
    return True

def trim700(t):
    if len(t) <= 700:
        return t
    cut = t[:700]
    i = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"), cut.rfind("\n"))
    return (cut[:i + 1] if i > 350 else cut).rstrip()

def llm_chat(url, headers, model, prompt):
    j = requests.post(url, timeout=120, headers=headers,
                      json={"model": model, "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 1024, "temperature": 0.7}).json()
    if "error" in j:
        raise RuntimeError(f"Ошибка API: {j['error'].get('message', '')[:120]}")
    return (j["choices"][0]["message"]["content"] or "").strip()

def split_img(t):
    if "IMG:" in t:
        a, b = t.split("IMG:", 1)
        return a.strip(), b.strip()[:200]
    return t, ""

def or_free_models():
    """Список бесплатных моделей OpenRouter. Исключаем 'рассуждалки' и агентные модели."""
    try:
        ms = requests.get("https://openrouter.ai/api/v1/models", timeout=30).json().get("data", [])
        bad_models = ["inkling", "nemotron", "r1", "reasoning", "think"]
        frees = [m["id"] for m in ms
                 if str(m["id"]).endswith(":free")
                 and not any(bm in str(m["id"]).lower() for bm in bad_models)]
        def rank(mid):
            midl = mid.lower()
            for i, pref in enumerate(["qwen/", "meta-llama/", "mistralai/", "deepseek/", "inclusionai/"]):
                if midl.startswith(pref):
                    return i
            return 9
        frees.sort(key=rank)
        return frees
    except Exception:
        return []

# ---------- Этап 1: список страниц ----------
try:
    xml = requests.get(SITEMAP, timeout=60, headers=UA).text
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
    sitemaps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
    urls = []
    for sm in sitemaps:
        x = requests.get(sm, timeout=60, headers=UA).text
        urls += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x)
                 if any(p in u for p in ["/catalog/", "/help/news/", "/help/articles/"])]
    urls = sorted(set(urls))
    if not urls:
        raise RuntimeError("не найдено ни одной страницы в разрешённых разделах")
    log("Этап 1 (sitemap)", "✅", f"страниц найдено: {len(urls)}")
except Exception as e:
    log("Этап 1 (sitemap)", "❌", str(e)); finish(); sys.exit(1)

# ---------- Этапы 2-3: случайная страница + контент + description ----------
try:
    hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
except Exception:
    hist = set()

title = body = page = desc = ""
for attempt in range(5):
    page = random.choice([u for u in urls if u not in hist] or urls)
    r = requests.get(page, timeout=60, headers=UA).text
    m = re.search(r"<h1[^>]*>(.*?)</h1>", r, re.S | re.I)
    title = clean(m.group(1)) if m else ""
    dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', r, re.S | re.I) \
         or re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']', r, re.S | re.I) \
         or re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', r, re.S | re.I)
    desc = clean(dm.group(1)) if dm else ""
    tail = r[m.end():] if m else r
    tail = re.sub(r"<script.*?</script>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<style.*?</style>", " ", tail, flags=re.S | re.I)
    tail = re.sub(r"<!--.*?-->", " ", tail, flags=re.S)
    for marker in ["Назад к списку", "Нужна консультация", "Подробная информация"]:
        i = tail.find(marker)
        if i != -1:
            tail = tail[:i]
    paras = re.findall(r"<p[^>]*>(.*?)</p>", tail, re.S | re.I)
    raw = " ".join(clean(p) for p in paras)
    if len(raw) < 100:
        raw = clean(tail)
    keep = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw)
            if len(s.strip()) >= 40 and "{" not in s and '"' not in s
            and not any(b in s for b in BLACKLIST)]
    body = " ".join(keep)[:1500]
    if title and "не найдена" not in title.lower() and (len(body) > 100 or len(desc) > 60):
        break
log("Этап 2 (случайная страница)", "✅", page)
log("Этап 3 (контент)", "✅" if (len(body) > 100 or len(desc) > 60) else "⚠️",
    f"«{title}», описание: {len(desc)} симв., чистого текста: {len(body)} симв.")

# ---------- Этап 4: ИИ-текст поста + описание картинки ----------
def template_text():
    base = desc or body
    sents = [s for s in re.split(r"(?<=[.!?])\s+", base) if 40 < len(s) < 220][:4]
    hook = random.choice([f"🚀 PAVRUS: {title}", f"💡 Интересное решение — {title}", f"📢 Новое на pavrus.ru: {title}"])
    tail = (f"\n\n🔗 Подробнее: {page}\n🏢 Оборудование для конференц-залов и переговорных\n"
            f"📩 Консультация: pavrus.ru\n#PAVRUS #АВоборудование")
    for n in range(len(sents), 0, -1):
        text = f"{hook}\n\n" + "\n".join("▪️ " + s for s in sents[:n]) + tail
        if 350 <= len(text) <= 700:
            return text
    text = f"{hook}\n\n▪️ {base[:500]}{tail}"
    if len(text) < 350:
        text += "\n\nПрофессиональное решение для бизнеса."
    return text[:700] if len(text) > 700 else text

prompt = (f"Ты SMM-маркетолог компании PAVRUS (оборудование для конференц-залов и переговорных). "
          f"Товар/материал: {title}. Описание с сайта: {desc} Дополнительный текст: {body} "
          f"Напиши ПОЛНОСТЬЮ СВОИМИ СЛОВАМИ живой продающий пост для ВКонтакте: НЕ копируй предложения с сайта, "
          f"передай суть и выгоды простыми словами, как будто рассказываешь клиенту. 350-700 символов, "
          f"2-4 коротких абзаца с эмодзи, в конце ссылка {page} и 2-3 хэштега. "
          f"В самом конце ответа добавь отдельную строку: IMG: и короткое (10-15 слов) описание фотографии "
          f"на АНГЛИЙСКОМ языке — как это оборудование выглядит в конференц-зале. Пиши только сам пост и строку IMG.")
text, src, img_hint = None, "", ""
if OR_KEY:
    for model in or_free_models()[:5]:
        try:
            a, b = split_img(llm_chat("https://openrouter.ai/api/v1/chat/completions",
                         {"Authorization": f"Bearer {OR_KEY}", "Content-Type": "application/json"},
                         model, prompt))
            a = a.replace("**", "").strip() # Убираем маркдаун-жирность
            if good_text(a):
                text, src = a, f"LLM (OpenRouter: {model})"
                if good_img(b):
                    img_hint = b
                break
        except Exception as e:
            log("Этап 4 (debug)", "⚠️", f"{model}: {str(e)[:120]}")

if not text and GROQ_KEY:
    try:
        a, b = split_img(llm_chat("https://api.groq.com/openai/v1/chat/completions",
                     {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                     "llama-3.3-70b-versatile", prompt))
        a = a.replace("**", "").strip()
        if good_text(a):
            text, src = a, "Groq LLM"
            if good_img(b): img_hint = b
    except Exception:
        pass

if not text:
    try:
        j = requests.post("https://text.pollinations.ai/openai", timeout=120,
                          json={"model": "openai", "messages": [{"role": "user", "content": prompt}]}).json()
        a, b = split_img((j.get("choices", [{}])[0].get("message", {}).get("content") or "").strip())
        a = a.replace("**", "").strip()
        if good_text(a):
            text, src = a, "LLM Pollinations"
            if good_img(b): img_hint = b
    except Exception:
        pass

if not text:
    text, src = template_text(), "шаблон (LLM недоступен)"
if page not in text:
    text += f"\n\n🔗 Подробнее: {page}"
text = trim700(text)
log("Этап 4 (текст поста)", "✅" if src != "шаблон (LLM недоступен)" else "⚠️", f"источник: {src}, {len(text)} симв.")

# ---------- Этап 5: картинка ----------
CATS = [("проектор", "video projector mounted in a conference room"),
        ("громкоговоритель", "ceiling loudspeaker in a conference room"),
        ("микрофон", "conference microphone on a table"),
        ("усилитель", "audio amplifier rack"),
        ("камер", "PTZ video camera in a conference room"),
        ("дисплей", "large display on a conference room wall"),
        ("панел", "LCD panel on a conference room wall"),
        ("микшер", "audio mixer console"),
        ("радиогид", "tour guide system with headsets")]

if img_hint:
    img_prompt = img_hint
else:
    low = (title + " " + desc + " " + body[:400]).lower()
    img_prompt = "AV equipment in a modern conference room"
    for ru, e in CATS:
        if ru in low:
            img_prompt = e
            break

img_bytes = b""
try:
    p = urllib.parse.quote(f"Professional photo: {img_prompt}, photorealistic, product: {title}")
    img_url = f"https://image.pollinations.ai/prompt/{p}?width=1200&height=800&nologo=true&seed={random.randint(1, 999999)}"
    resp = requests.get(img_url, timeout=180)
    if resp.headers.get("content-type", "").startswith("image"):
        img_bytes = resp.content
        log("Этап 5 (картинка)", "✅", f"{len(img_bytes)} байт, промпт: {img_prompt[:60]}")
    else:
        log("Этап 5 (картинка)", "⚠️", "сервер вернул не изображение")
except Exception as e:
    log("Этап 5 (картинка)", "⚠️", str(e))

# ---------- Этап 6: публикация в ВК ----------
def vk(method, token=None, **kw):
    kw.update(access_token=token or VK_TOKEN, v="5.131")
    j = requests.post(f"https://api.vk.com/method/{method}", data=kw, timeout=60).json()
    if "error" in j:
        raise RuntimeError(f"[{j['error']['error_code']}] {j['error'].get('error_msg')}")
    return j["response"]

try:
    if not VK_TOKEN:
        raise RuntimeError("не задан VK_TOKEN в Secrets")
    gid = VK_GROUP
    if not gid.isdigit():
        gid = str(vk("groups.getById", group_id=gid)[0]["id"])
    att, how = "", ""
    if img_bytes:
        if VK_USER_TOKEN:
            try:
                up = vk("photos.getWallUploadServer", group_id=gid, token=VK_USER_TOKEN)["upload_url"]
                j = requests.post(up, files={"photo": ("img.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
                errs = []
                p = None
                for extra in [{"group_id": gid}, {}]:
                    try:
                        p = vk("photos.saveWallPhoto", token=VK_USER_TOKEN,
                               photo=j.get("photo", ""), server=j.get("server", ""),
                               hash=j.get("hash", ""), **extra)[0]
                        break
                    except Exception as e2:
                        errs.append(str(e2))
                if p is None:
                    raise RuntimeError(" | ".join(errs))
                att, how = f"photo{p['owner_id']}_{p['id']}", "фото (токен владельца)"
            except Exception as e:
                log("Этап 6а", "⚠️", f"токен владельца: {e}")
        if not att:
            try:
                up = vk("photos.getWallUploadServer", group_id=gid)["upload_url"]
                j = requests.post(up, files={"photo": ("img.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
                p = vk("photos.saveWallPhoto", group_id=gid, photo=j["photo"], server=j["server"], hash=j["hash"])[0]
                att, how = f"photo{p['owner_id']}_{p['id']}", "фото"
            except Exception:
                try:
                    aid = None
                    for a in vk("photos.getAlbums", group_id=gid)["items"]:
                        if a["title"] == "agent-images":
                            aid = a["id"]; break
                    if aid is None:
                        aid = vk("photos.createAlbum", group_id=gid, title="agent-images",
                                 description="Изображения для постов")["id"]
                    up = vk("photos.getUploadServer", group_id=gid, album_id=aid)["upload_url"]
                    j = requests.post(up, files={"photo": ("img.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
                    params = {k: j[k] for k in ("photo", "photos_list", "server", "hash") if k in j}
                    p = vk("photos.save", group_id=gid, album_id=aid, **params)[0]
                    att, how = f"photo{p['owner_id']}_{p['id']}", "фото из альбома"
                except Exception:
                    pass
        if att:
            log("Этап 6а (загрузка фото)", "✅", f"сгенерированная картинка прикреплена как {how}")
        else:
            log("Этап 6а (загрузка фото)", "⚠️", "ВК отклонил загрузку — пост выйдет со ссылкой")
    post = vk("wall.post", owner_id="-" + gid,
              message=text, attachments=att, random_id=random.randint(1, 2**31))
    link = f"https://vk.com/wall-{gid}_{post['post_id']}"
    log("Этап 6 (публикация ВК)", "✅", link)
    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
except Exception as e:
    log("Этап 6 (публикация ВК)", "❌", str(e))

finish()
