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
    if not t or len(t) < 350:
        return False
    bad = ['"error"', "Payment Required", "pollen", "deprecation_notice", "<html", "<!DOCTYPE", "{", "@context"]
    if t.lstrip().startswith("{") or any(b in t for b in bad):
        return False
    think = ["thinking process", "analyze the request", "constraints:", "**role", "source text:",
             "here's a thinking", "
