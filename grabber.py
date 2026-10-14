import re
import json
import os
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://nashr.majles.ir/"
DATA_FILE = "downloaded_articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

# عبارات عمومی/منویی که نباید به عنوان "عنوان مقاله" انتخاب شوند
IGNORE_PHRASES = [
    "مقالات آماده انتشار",
    "شماره جاری",
    "شماره‌های پیشین نشریه",
    "مقاله پژوهشی",
    "مقاله ترویجی",
    "مقاله مروری",
    "مشاهده مقاله",
    "اصل مقاله",
    "فایل کلی",
    "جستجو",
    "جستجوی پیشرفته",
    "شناسنامه نشریه",
    "بانک ها و نمایه نامه ها",
]

def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())

def is_bad_title(text: str) -> bool:
    t = normalize_spaces(text)
    if not t:
        return True
    if len(t) < 8:
        return True
    # DOI یا صفحه/متادیتا نباشد
    if re.search(r"10\.\d{4,9}/", t):
        return True
    if t.startswith("صفحه"):
        return True
    if any(p in t for p in IGNORE_PHRASES):
        return True
    # مواردی مثل "5.43 M" یا "4.79 M" که کنار اصل مقاله می‌آید
    if re.fullmatch(r"\d+(\.\d+)?\s*[Mm]", t):
        return True
    return False

def extract_article_id_from_doi_url(doi_url: str) -> str:
    m = re.search(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", doi_url or "")
    return m.group(1) if m else (doi_url or "")

def extract_title_near_doi_anchor(doi_a_tag) -> str:
    """
    در صفحه نشریه، ساختار به این شکل است:
    [عنوان مقاله] ... سپس DOI (به صورت متن/لینک) و سپس "اصل مقاله"
    بهترین راه کم‌خطا: از خود تگ DOI شروع کنیم و به عقب در DOM دنبال نزدیک‌ترین متنِ معنی‌دار بگردیم.
    """

    # 1) اول تلاش: در همان بلوک پدر (container) عنوان را پیدا کنیم
    container = doi_a_tag.find_parent(["div", "li", "tr", "section", "article"])
    candidates = []

    if container:
        # همه متن‌های داخل container را به ترتیب ظهور جمع می‌کنیم
        # ولی معمولاً عنوان در تگ‌های مستقل (h*, strong, p, div, span) است
        for el in container.find_all(["h1","h2","h3","h4","h5","strong","p","div","span","a"], recursive=True):
            txt = normalize_spaces(el.get_text(" ", strip=True))
            if not is_bad_title(txt):
                candidates.append(txt)

        # چون داخل container ممکن است نام نویسندگان هم بیاید،
        # معمولاً "اولین متن بلند و معنی‌دار" همان عنوان است
        if candidates:
            # قاعده عملی: بلندترینِ چند گزینه اول معمولاً عنوان است
            top = candidates[:8]
            top.sort(key=len, reverse=True)
            return 
