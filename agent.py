

# -*- coding: utf-8 -*-
import os, re, json, html, random, sys
import urllib.parse
import requests

SITE = "https://pavrus.ru"
SITEMAP = SITE + "/sitemap.xml"
HISTORY = "history.json"
UA = {"User-Agent": "Mozilla/5.0 (pavrus-vk-agent)"}

VK_TOKEN = os.getenv("VK_TOKEN", "")
VK_GROUP = os.getenv("VK_GROUP_ID", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

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
        except Exception: pass

def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()

def good_text(t):
    """Проверка: нейросеть должна вернуть текст, а не JSON с ошибкой."""
    if not t or len(t) < 100 or len(t) > 2500: return False
    bad = ['"error"', "Payment Required", "pollen", "deprecation_notice", "<html", "<!DOCTYPE"]
    if t.lstrip().startswith("{") or any(b in t for b in bad): return False
    return True

# ---------- Этап 1: список страниц ----------
try:
    xml = requests.get(SITEMAP, timeout=60, headers=UA).text
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
    sitemaps = [l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
    urls = []
    for sm in sitemaps:
        x = requests.get(sm, timeout=60, headers=UA).text
        urls += [u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", x) if "/help/" in u]
    urls = sorted(set(urls))
    log("Этап 1 (sitemap)", "✅", f"страниц найдено: {len(urls)}")
except Exception as e:
    log("Этап 1 (sitemap)", "❌", str(e)); finish(); sys.exit(1)

# ---------- Этапы 2-3: случайная страница + контент (пропуск 404) ----------
try:
    hist = set(json.load(open(HISTORY, encoding="utf-8"))) if os.path.exists(HISTORY) else set()
except Exception:
    hist = set()

title = body = page = ""
for attempt in range(5):
    page = random.choice([u for u in urls if u not in hist] or urls)
    r = requests.get(page, timeout=60, headers=UA).text
    m = re.search(r"<h1[^>]*>(.*?)</h1>", r, re.S | re.I)
    title = clean(m.group(1)) if m else ""
    paras = [clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", r, re.S | re.I)]
    body = " ".join(p for p in paras if len(p) > 40)[:2000]
    if title and "не найдена" not in title.lower() and len(body) > 100:
        break
log("Этап 2 (случайная страница)", "✅", page)
log("Этап 3 (контент)", "✅" if len(body) > 100 else "⚠️", f"«{title}», текста: {len(body)} симв.")

# ---------- Этап 4: генерация текста поста ----------
def template_text():
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 30][:4]
    hook = random.choice([
        f"🚀 PAVRUS: {title}",
        f"💡 Интересное решение — {title}",
        f"📢 Новое на pavrus.ru: {title}",
    ])
    bullets = "\n".join("▪️ " + s for s in sents) if sents else "▪️ " + body[:400]
    return (f"{hook}\n\n{bullets}\n\n"
            "🏢 Оборудование для конференц-залов, переговорных и ситуационных центров — подбор и монтаж под ключ.\n"
            f"📩 Консультация: pavrus.ru\n🔗 Подробнее: {page}\n\n"
            "#PAVRUS #АВоборудование #видеоконференции #конференцзал")

text, src = None, ""
prompt = (f"Напиши привлекательный пост для ВКонтакте на русском по материалу: {title}. {body} "
          f"Формат: 4-6 коротких пунктов с эмодзи, в конце хэштеги и ссылка {page}. До 1000 символов.")
try:
    j = requests.post("https://text.pollinations.ai/openai", timeout=120,
                      json={"model": "openai", "messages": [{"role": "user", "content": prompt}]}).json()
    t = (j.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    if good_text(t): text, src = t, "LLM Pollinations"
except Exception:
    pass
if not text:
    try:
        t = requests.get("https://text.pollinations.ai/" + urllib.parse.quote(prompt), timeout=120).text.strip()
        if good_text(t): text, src = t, "LLM Pollinations (GET)"
    except Exception:
        pass
if not text:
    text, src = template_text(), "шаблон (LLM недоступен)"
if page not in text:
    text += f"\n\n🔗 Подробнее: {page}"
log("Этап 4 (текст поста)", "✅" if "LLM" in src else "⚠️", f"источник: {src}, {len(text)} симв.")

# ---------- Этап 5: генерация картинки ----------
img_bytes = b""
try:
    p = urllib.parse.quote(f"Professional photo: {title}, modern conference room, AV equipment, photorealistic")
    img_url = f"https://image.pollinations.ai/prompt/{p}?width=1200&height=800&nologo=true&seed={random.randint(1, 999999)}"
    resp = requests.get(img_url, timeout=180)
    if resp.headers.get("content-type", "").startswith("image"):
        img_bytes = resp.content
        log("Этап 5 (картинка)", "✅", f"{len(img_bytes)} байт")
    else:
        log("Этап 5 (картинка)", "⚠️", "сервер вернул не изображение")
except Exception as e:
    log("Этап 5 (картинка)", "⚠️", str(e))

# ---------- Этап 6: публикация в ВК ----------
def vk(method, **kw):
    kw.update(access_token=VK_TOKEN, v="5.131")
    j = requests.post(f"https://api.vk.com/method/{method}", data=kw, timeout=60).json()
    if "error" in j: raise RuntimeError(f"[{j['error']['error_code']}] {j['error'].get('error_msg')}")
    return j["response"]

try:
    if not VK_TOKEN: raise RuntimeError("не задан VK_TOKEN в Secrets")
    gid = VK_GROUP
    if not gid.isdigit():
        gid = str(vk("groups.getById", group_id=gid)[0]["id"])
    att = ""
    if img_bytes:
        try:
            up = vk("photos.getWallUploadServer", group_id=gid)["upload_url"]
            j = requests.post(up, files={"photo": ("img.jpg", img_bytes, "image/jpeg")}, timeout=120).json()
            p = vk("photos.saveWallPhoto", group_id=gid, photo=j["photo"], server=j["server"], hash=j["hash"])[0]
            att = f"photo{p['owner_id']}_{p['id']}"
            log("Этап 6а (загрузка фото)", "✅", "картинка прикреплена")
        except Exception as e:
            log("Этап 6а (загрузка фото)", "⚠️", f"ВК не даёт грузить фото токеном сообщества — пост выйдет со ссылкой (превью с фото сайта): {e}")
    post = vk("wall.post", owner_id="-" + gid,
              message=text, attachments=att, random_id=random.randint(1, 2**31))
    link = f"https://vk.com/wall-{gid}_{post['post_id']}"
    log("Этап 6 (публикация ВК)", "✅", link)
    hist.add(page)
    json.dump(sorted(hist), open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
except Exception as e:
    log("Этап 6 (публикация ВК)", "❌", str(e))

finish()
