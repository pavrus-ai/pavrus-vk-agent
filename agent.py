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
            log(f"⚠️ Попытка {i+1}: 404 — {u}")
            continue
        if rs.status_code != 200 or len(rs.text) < 3000:
            log(f"⚠️ Попытка {i+1}: HTTP {rs.status_code} — {u}")
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
            log("⚠️ Картинка товара недоступна — генерирую")
            img = generate_product_image(title, desc)
        
        if not img:
            log(f"⚠️ Попытка {i+1}: не удалось получить картинку — {u}")
            continue
        
        img = ensure_size(img, 1000)
        page = u
        log(f"✅ Попытка {i+1}: товар «{title[:70]}» с картинкой — {page}")
        break
    
    if site_down:
        log("❌ Сайт pavrus.ru недоступен — агент останавливается")
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
    
    # ПРОМПТ БЕЗ ССЫЛКИ
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
        f"5. В конце добавь призыв: «Напишите нам в сообщения группы — расскажем подробнее и подберём решение под ваш проект».\n"
        f"6. Без хэштегов.\n"
        f"7. НИКАКИХ ссылок в тексте — ни внутренних, ни внешних."
    )
    
    text = ai_call(prompt, 400)
    if not text:
        log("⏳ Все ИИ молчат — пауза 30 сек и повтор")
        time.sleep(30)
        text = ai_call(prompt, 400)
    
    if not text:
        # Фолбэк БЕЗ ссылки
        base = body[:900] or desc
        text = f"{title}\n\n{base}\n\nНапишите нам в сообщения группы — расскажем подробнее и подберём решение под ваш проект."
        log("⚠️ Все ступени ИИ недоступны — фолбэк из текста страницы")
    
    # Очистка текста
    text = text.replace("**", "").replace("##", "").strip()
    
    # Удаляем ссылки, если ИИ всё же их добавил
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"pavrus\.ru\S*", "", text, flags=re.I)
    text = re.sub(r"Подробнее:\s*", "", text, flags=re.I)
    
    # Обрезка БЕЗ ссылки
    if len(text) > 1500:
        text = text[:1500].rsplit(" ", 1)[0].rstrip() + "\n\nНапишите нам в сообщения группы — расскажем подробнее!"
    
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
