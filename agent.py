
# -*- coding: utf-8 -*-
import os, re, json, html, random, sys, urllib.parse, requests
SITE="https://pavrus.ru"; SITEMAP=SITE+"/sitemap.xml"; HISTORY="history.json"
UA={"User-Agent":"Mozilla/5.0 (pavrus-vk-agent)"}
VK_TOKEN=os.getenv("VK_TOKEN",""); VK_USER_TOKEN=os.getenv("VK_USER_TOKEN","")
VK_GROUP=os.getenv("VK_GROUP_ID","")
TG_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN",""); TG_CHAT=os.getenv("TELEGRAM_CHAT_ID","")
OR_KEY=os.getenv("OPENROUTER_KEY",""); GROQ_KEY=os.getenv("GROQ_KEY","")
BL=["Корзина","Кабинет","Избранные","Сравнение","Каталог","Войти","Заказать звонок",
    "Санкт-Петербург","Москва","Новосибирск","Краснодар","Красноярск","8 (800)","info@",
    "pavrus.ru","Показать еще","Ваш город","Да, спасибо","Нет, другой","Выбрать автоматически",
    "Бесплатная доставка","Главная","HTDZ","AUDAC","CVID","CHIAYO","Restmoment","радиогид",
    "PAVRUS PA-","PAVRUS ABK","E-Desk","таблички","громкоговорители","инфракрасная",
    "@context","@type","schema.org",'description":',"Обратная связь"]
rep=[]
def log(s,st,m):
    l=f"{s} {st} {m}"; print(l,flush=True); rep.append(l)
def finish():
    if TG_TOKEN and TG_CHAT:
        try: requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
              json={"chat_id":TG_CHAT,"text":"\n".join(rep)},timeout=30)
        except: pass
def clean(s):
    for _ in range(3):
        s=html.unescape(s)
        s=re.sub(r"<[^>]+>"," ",s)
    return re.sub(r"\s+"," ",s).strip()
def good_text(t):
    if not t or len(t)<350: return False
    bad=['"error"',"Payment Required","pollen","<html","<!DOCTYPE","{","@context","</span"]
    if t.lstrip().startswith("{") or any(b in t for b in bad): return False
    th=["thinking process","analyze the request","constraints:","source text:",
        "here's a thinking","<think>","additional text:","1. analyze"]
    return not any(m in t.lower() for m in th)
def good_img(b):
    if not b or len(b)<10 or len(b)>200: return False
    lo=b.lower()
    for bad in ["description in english","short (10-15","of how this","words) description"]:
        if bad in lo: return False
    return True
def score(t):
    s=0; n=len(t)
    if 350<=n<=700: s+=2
    if 450<=n<=650: s+=1
    s+=min(len(re.findall(r"[\U0001F300-\U0001FAFF]",t)),4)
    s+=min(len([p for p in t.split("\n") if p.strip()]),4)
    if len(re.findall(r"[а-яё]",t.lower()))>100: s+=2
    if "**" in t: s-=2
    return s
def trim(t):
    if len(t)<=700: return t
    c=t[:700]; i=max(c.rfind("."),c.rfind("!"),c.rfind("?"),c.rfind("\n"))
    return (c[:i+1] if i>350 else c).rstrip()
def chat(url,h,m,p,mt=1024):
    j=requests.post(url,timeout=120,headers=h,
        json={"model":m,"messages":[{"role":"user","content":p}],
              "max_tokens":mt,"temperature":0.7}).json()
    if "error" in j: raise RuntimeError(f"API: {j['error'].get('message','')[:120]}")
    return (j["choices"][0]["message"]["content"] or "").strip()
def sp(t):
    if "IMG:" in t:
        a,b=t.split("IMG:",1); return a.strip(),b.strip()[:200]
    return t,""
def orf():
    try:
        ms=requests.get("https://openrouter.ai/api/v1/models",timeout=30).json().get("data",[])
        bd=["inkling","nemotron","r1","reasoning","think"]
        fr=[m["id"] for m in ms if str(m["id"]).endswith(":free")
            and not any(b in str(m["id"]).lower() for b in bd)]
        def rk(m):
            lo=m.lower()
            for i,p in enumerate(["qwen/","meta-llama/","mistralai/","deepseek/","inclusionai/"]):
                if lo.startswith(p): return i
            return 9
        fr.sort(key=rk); return fr
    except: return []
# --- Этап 1 ---
try:
    xml=requests.get(SITEMAP,timeout=60,headers=UA).text
    locs=re.findall(r"<loc>\s*(.*?)\s*</loc>",xml)
    smps=[l for l in locs if "sitemap" in l.lower()] or [SITEMAP]
    urls=[]
    for sm in smps:
        x=requests.get(sm,timeout=60,headers=UA).text
        urls+=[u for u in re.findall(r"<loc>\s*(.*?)\s*</loc>",x)
               if any(p in u for p in ["/catalog/","/help/news/","/help/articles/"])]
    urls=sorted(set(urls))
    if not urls: raise RuntimeError("не найдено страниц")
    log("Этап 1","✅",f"страниц: {len(urls)}")
except Exception as e: log("Этап 1","❌",str(e)); finish(); sys.exit(1)
# --- Этапы 2-3 ---
try: hist=set(json.load(open(HISTORY,encoding="utf-8"))) if os.path.exists(HISTORY) else set()
except: hist=set()
title=body=page=desc=""
for _ in range(5):
    page=random.choice([u for u in urls if u not in hist] or urls)
    r=requests.get(page,timeout=60,headers=UA).text
    m=re.search(r"<h1[^>]*>(.*?)</h1>",r,re.S|re.I)
    title=clean(m.group(1)) if m else ""
    dm=re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',r,re.S|re.I) \
       or re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',r,re.S|re.I) \
       or re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',r,re.S|re.I)
    desc=clean(dm.group(1)) if dm else ""
    tail=r[m.end():] if m else r
    tail=re.sub(r"<script.*?</script>"," ",tail,flags=re.S|re.I)
    tail=re.sub(r"<style.*?</style>"," ",tail,flags=re.S|re.I)
    tail=re.sub(r"<!--.*?-->"," ",tail,flags=re.S)
    for mk in ["Назад к списку","Нужна консультация","Подробная информация"]:
        i=tail.find(mk)
        if i!=-1: tail=tail[:i]
    paras=re.findall(r"<p[^>]*>(.*?)</p>",tail,re.S|re.I)
    raw=" ".join(clean(p) for p in paras)
    if len(raw)<100: raw=clean(tail)
    keep=[s.strip() for s in re.split(r"(?<=[.!?])\s+",raw)
          if len(s.strip())>=40 and "{" not in s and '"' not in s and not any(b in s for b in BL)]
    body=" ".join(keep)[:1500]
    if title and "не найдена" not in title.lower() and (len(body)>100 or len(desc)>60): break
log("Этап 2","✅",page)
log("Этап 3","✅" if (len(body)>100 or len(desc)>60) else "⚠️",
    f"«{title}», desc: {len(desc)}, text: {len(body)}")
# --- Этап 4: битва двух ИИ ---
def tpl():
    base=desc or body
    sents=[s for s in re.split(r"(?<=[.!?])\s+",base) if 40<len(s)<220][:4]
    hook=random.choice([f"🚀 PAVRUS: {title}",f"💡 {title}",f"📢 {title}"])
    tail=f"\n\n🔗 {page}\n🏢 Оборудование для конференц-залов\n📩 pavrus.ru\n#PAVRUS #АВоборудование"
    for n in range(len(sents),0,-1):
        t=f"{hook}\n\n"+"\n".join("▪️ "+s for s in sents[:n])+tail
        if 350<=len(t)<=700: return t
    t=f"{hook}\n\n▪️ {base[:500]}{tail}"
    if len(t)<350: t+="\n\nПрофессиональное решение."
    return t[:700]
pr=(f"Ты SMM-маркетолог PAVRUS (оборудование для конференц-залов). "
    f"Товар: {title}. Описание: {desc} Текст: {body} "
    f"Напиши ПОЛНОСТЬЮ СВОИМИ СЛОВАМИ продающий пост для ВКонтакте: НЕ копируй с сайта, "
    f"передай суть и выгоды. 350-700 символов, 2-4 абзаца с эмодзи, в конце {page} и хэштеги. "
    f"В самом конце строку IMG: и 10-15 слов описания фото на АНГЛИЙСКОМ — как оборудование в конференц-зале. "
    f"Пиши только пост и строку IMG.")
cands=[]
if OR_KEY:
    for m in orf()[:3]:
        try:
            a,b=sp(chat("https://openrouter.ai/api/v1/chat/completions",
                {"Authorization":f"Bearer {OR_KEY}","Content-Type":"application/json"},m,pr))
            a=a.replace("**","").strip()
            if good_text(a): cands.append((a,f"OR({m})",b)); break
        except Exception as e: log("Этап 4(debug)","⚠️",f"OR {m}: {str(e)[:100]}")
if GROQ_KEY:
    gm=None
    try:
        ms=requests.get("https://api.groq.com/openai/v1/models",timeout=30,
            headers={"Authorization":f"Bearer {GROQ_KEY}"}).json().get("data",[])
        ids=[m["id"] for m in ms]
        for p in ["llama-3.3-70b","llama-3.1-8b","llama",""]:
            gm=next((i for i in ids if i.startswith(p)),None)
            if gm: break
    except: gm=None
    if gm:
        try:
            a,b=sp(chat("https://api.groq.com/openai/v1/chat/completions",
               {"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},gm,pr,512))
            a=a.replace("**","").strip()
            if good_text(a): cands.append((a,f"Groq({gm})",b))
        except Exception as e: log("Этап 4(debug)","⚠️",f"Groq: {str(e)[:100]}")
text=src=img_hint=""
if cands:
    cands.sort(key=lambda c:score(c[0]),reverse=True)
    text,src,ri=cands[0]
    img_hint=ri if good_img(ri) else ""
    if len(cands)>1:
        log("Этап 4 (сравнение)","ℹ️",
            " | ".join(f"{c[1]}:{score(c[0])}" for c in cands)+f" → {src}")
if not text: text,src=tpl(),"шаблон"
if page not in text: text+=f"\n\n🔗 {page}"
text=trim(text)
log("Этап 4","✅" if src!="шаблон" else "⚠️",f"{src}, {len(text)} симв.")
# --- Этап 5: картинка ---
CAT=[("проектор","video projector mounted in a conference room"),
     ("громкоговоритель","ceiling loudspeaker in a conference room"),
     ("микрофон","conference microphone on a table"),
     ("усилитель","audio amplifier rack"),
     ("камер","PTZ video camera in a conference room"),
     ("дисплей","large display on a conference room wall"),
     ("панел","LCD panel on a conference room wall"),
     ("микшер","audio mixer console"),
     ("радиогид","tour guide system with headsets")]
if img_hint: ip=img_hint
else:
    lo=(title+" "+desc+" "+body[:400]).lower()
    ip="AV equipment in a modern conference room"
    for ru,e in CAT:
        if ru in lo: ip=e; break
img_bytes=b""
try:
    p=urllib.parse.quote(f"Professional photo: {ip}, photorealistic, product: {title}")
    u=f"https://image.pollinations.ai/prompt/{p}?width=1200&height=800&nologo=true&seed={random.randint(1,999999)}"
    resp=requests.get(u,timeout=180)
    if resp.headers.get("content-type","").startswith("image"):
        img_bytes=resp.content
        log("Этап 5","✅",f"{len(img_bytes)} байт, {ip[:60]}")
    else: log("Этап 5","⚠️","не изображение")
except Exception as e: log("Этап 5","⚠️",str(e))
# --- Этап 6: ВК ---
def vk(method,token=None,**kw):
    kw.update(access_token=token or VK_TOKEN,v="5.131")
    j=requests.post(f"https://api.vk.com/method/{method}",data=kw,timeout=60).json()
    if "error" in j: raise RuntimeError(f"[{j['error']['error_code']}] {j['error'].get('error_msg')}")
    return j["response"]
try:
    if not VK_TOKEN: raise RuntimeError("нет VK_TOKEN")
    gid=VK_GROUP
    if not gid.isdigit(): gid=str(vk("groups.getById",group_id=gid)[0]["id"])
    att=how=""
    if img_bytes:
        if VK_USER_TOKEN:
            try:
                up=vk("photos.getWallUploadServer",group_id=gid,token=VK_USER_TOKEN)["upload_url"]
                j=requests.post(up,files={"photo":("i.jpg",img_bytes,"image/jpeg")},timeout=120).json()
                errs=[]; p=None
                for ex in [{"group_id":gid},{}]:
                    try:
                        p=vk("photos.saveWallPhoto",token=VK_USER_TOKEN,
                            photo=j.get("photo",""),server=j.get("server",""),hash=j.get("hash",""),**ex)[0]
                        break
                    except Exception as e2: errs.append(str(e2))
                if p is None: raise RuntimeError(" | ".join(errs))
                att,how=f"photo{p['owner_id']}_{p['id']}","токен владельца"
            except Exception as e: log("Этап 6а","⚠️",f"токен владельца: {e}")
        if not att:
            try:
                up=vk("photos.getWallUploadServer",group_id=gid)["upload_url"]
                j=requests.post(up,files={"photo":("i.jpg",img_bytes,"image/jpeg")},timeout=120).json()
                p=vk("photos.saveWallPhoto",group_id=gid,photo=j["photo"],server=j["server"],hash=j["hash"])[0]
                att,how=f"photo{p['owner_id']}_{p['id']}","фото"
            except:
                try:
                    aid=None
                    for a in vk("photos.getAlbums",group_id=gid)["items"]:
                        if a["title"]=="agent-images": aid=a["id"]; break
                    if aid is None:
                        aid=vk("photos.createAlbum",group_id=gid,title="agent-images",
                               description="Изображения для постов")["id"]
                    up=vk("photos.getUploadServer",group_id=gid,album_id=aid)["upload_url"]
                    j=requests.post(up,files={"photo":("i.jpg",img_bytes,"image/jpeg")},timeout=120).json()
                    pk={k:j[k] for k in ("photo","photos_list","server","hash") if k in j}
                    p=vk("photos.save",group_id=gid,album_id=aid,**pk)[0]
                    att,how=f"photo{p['owner_id']}_{p['id']}","альбом"
                except: pass
        if att: log("Этап 6а","✅",how)
        else: log("Этап 6а","⚠️","отклонено — пост со ссылкой")
    post=vk("wall.post",owner_id="-"+gid,message=text,attachments=att,random_id=random.randint(1,2**31))
    link=f"https://vk.com/wall-{gid}_{post['post_id']}"
    log("Этап 6","✅",link)
    hist.add(page); json.dump(sorted(hist),open(HISTORY,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
except Exception as e: log("Этап 6","❌",str(e))
finish()

